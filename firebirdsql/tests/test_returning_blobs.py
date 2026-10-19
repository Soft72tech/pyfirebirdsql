import asyncio
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from firebirdsql.consts import SQL_TYPE_BLOB, SQL_TYPE_LONG, isc_info_sql_stmt_exec_procedure
from firebirdsql.fbcore import Cursor, Statement
from firebirdsql.aio.fbcore import AsyncCursor, AsyncStatement


class SingletonBlobTest(unittest.TestCase):
    def fixture(self, async_):
        connection = Mock()
        connection._cursors = {}
        connection.accept_type = 0
        connection.db_handle = 1
        connection.bytes_to_str = lambda value: value.decode('utf-8')
        transaction = Mock(connection=connection, trans_handle=2, _trans_handle=2)
        transaction.is_dirty = True
        row = [b'binaryid', b'textblob', None, 42]
        responses = [(0, b'', b''), (101, b'', b''),
                     (2, b'', b'\x03\x00abc'), (0, b'', b''),
                     (102, b'', b''), (2, b'', b'\x02\x00\xc3\xa9'),
                     (0, b'', b'')]
        statement = SimpleNamespace(
            handle=3, trans=transaction,
            stmt_type=isc_info_sql_stmt_exec_procedure,
            xsqlda=[SimpleNamespace(sqltype=SQL_TYPE_BLOB, sqlsubtype=subtype)
                    for subtype in (0, 1, 0)] +
                   [SimpleNamespace(sqltype=SQL_TYPE_LONG, sqlscale=0)])
        if async_:
            cursor = object.__new__(AsyncCursor)
            cursor._get_stmt = AsyncMock(return_value=statement)
            transaction.check_trans_handle = AsyncMock()
            connection._async_op_sql_response = AsyncMock(return_value=row)
            connection._async_op_response = AsyncMock(side_effect=responses)
            statement.fetch_generator = MethodType(AsyncStatement.fetch_generator, statement)
        else:
            cursor = object.__new__(Cursor)
            cursor._get_stmt = Mock(return_value=statement)
            connection._op_sql_response = Mock(return_value=row)
            connection._op_response = Mock(side_effect=responses)
            statement.fetch_generator = MethodType(Statement.fetch_generator, statement)
        cursor._transaction = transaction
        return cursor, connection, row

    def test_sync_singleton_materializes_binary_text_and_null(self):
        cursor, connection, original = self.fixture(False)
        with patch('firebirdsql.fbcore.calc_blr', return_value=b'blr'):
            cursor.execute('INSERT ... RETURNING ...')
        self.assertEqual(cursor.fetchone(), [b'abc', 'é', None, 42])
        self.assertIsNone(cursor.fetchone())
        self.assertEqual(original, [b'binaryid', b'textblob', None, 42])
        self.assertEqual(connection._op_open_blob2.call_count, 2)
        self.assertEqual(connection._op_close_blob.call_count, 2)

    def test_async_singleton_awaits_blob_reads(self):
        async def run():
            cursor, connection, original = self.fixture(True)
            with patch('firebirdsql.aio.fbcore.calc_blr', return_value=b'blr'):
                await cursor.execute('INSERT ... RETURNING ...')
            self.assertEqual(await cursor.fetchone(), [b'abc', 'é', None, 42])
            self.assertIsNone(await cursor.fetchone())
            self.assertEqual(original, [b'binaryid', b'textblob', None, 42])
            self.assertEqual(connection._async_op_response.await_count, 7)
            self.assertEqual(connection._op_close_blob.call_count, 2)
        asyncio.run(run())
