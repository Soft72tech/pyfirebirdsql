"""SQLDA continuation protocol regression tests without a live server."""
import unittest
from unittest.mock import Mock

from firebirdsql.consts import (
    isc_info_end, isc_info_truncated, isc_info_sql_bind,
    isc_info_sql_select, isc_info_sql_describe_vars, isc_info_sql_describe_end,
    isc_info_sql_sqlda_seq, isc_info_sql_sqlda_start, isc_info_sql_type,
    isc_info_sql_length, SQL_TYPE_LONG,
)
from firebirdsql.utils import int_to_bytes
from firebirdsql.wireprotocol import (
    INFO_SQL_BIND_DESCRIBE_VARS, INFO_SQL_SELECT_DESCRIBE_VARS,
)
from firebirdsql.xsqlvar import parse_xsqlda


def item(code, value):
    return bytes([code, 4, 0]) + int_to_bytes(value, 4)


def header(section, count):
    return bytes([section]) + item(isc_info_sql_describe_vars, count)


def variable(index):
    return (item(isc_info_sql_sqlda_seq, index)
            + item(isc_info_sql_type, SQL_TYPE_LONG + 1)
            + item(isc_info_sql_length, 4))


class BindMetadataTest(unittest.TestCase):
    def test_multiple_continuations_resume_partial_variable(self):
        for section, request in (
            (isc_info_sql_bind, INFO_SQL_BIND_DESCRIBE_VARS),
            (isc_info_sql_select, INFO_SQL_SELECT_DESCRIBE_VARS),
        ):
            with self.subTest(section=section):
                connection = Mock()
                connection.bytes_to_str = lambda value: value.decode('utf8')
                connection._op_response.side_effect = [
                    (0, b'', header(section, 2) + variable(1)
                     + item(isc_info_sql_sqlda_seq, 2)
                     + bytes([isc_info_truncated])),
                    (0, b'', header(section, 2) + variable(2)
                     + bytes([isc_info_sql_describe_end, isc_info_end])),
                ]
                # Initial response truncates in the first variable; its partial
                # metadata must be replaced when that variable is requested again.
                buf = (header(section, 2) + item(isc_info_sql_sqlda_seq, 1)
                       + bytes([isc_info_truncated]))
                _, output, binds = parse_xsqlda(buf, connection, 42)
                metadata = binds if section == isc_info_sql_bind else output
                self.assertEqual([x.sqltype for x in metadata], [SQL_TYPE_LONG] * 2)
                self.assertEqual([x.sqllen for x in metadata], [4, 4])
                self.assertEqual(output if section == isc_info_sql_bind else binds, [])
                self.assertEqual(connection._op_info_sql.call_args_list, [
                    ((42, bytes([isc_info_sql_sqlda_start, 2])
                      + int_to_bytes(index, 2) + request),)
                    for index in (1, 2)
                ])

    def test_zero_bind_count_after_select_metadata(self):
        connection = Mock()
        connection.bytes_to_str = lambda value: value.decode('utf8')
        buf = (header(isc_info_sql_select, 1) + variable(1)
               + bytes([isc_info_sql_describe_end])
               + header(isc_info_sql_bind, 0) + bytes([isc_info_end]))
        _, output, binds = parse_xsqlda(buf, connection, 42)
        self.assertEqual(output[0].sqltype, SQL_TYPE_LONG)
        self.assertEqual(binds, [])
        connection._op_info_sql.assert_not_called()
