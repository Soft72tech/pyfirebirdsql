"""Malformed diagnostic text must not leave the wire response unread."""
import asyncio
import struct
import unittest

from firebirdsql.consts import isc_arg_end, isc_arg_gds, isc_arg_string
from firebirdsql.err import OperationalError
from firebirdsql.fbcore import ConnectionResponseMixin
from firebirdsql.aio.fbcore import AsyncConnectionResponseMixin
from firebirdsql.wireprotocol import WireProtocol


class Response(AsyncConnectionResponseMixin, WireProtocol):
    charset = 'UTF8'

    def __init__(self, value):
        self.buffer = bytearray(value)

    def _recv_channel(self, size, word_alignment=False):
        consumed = (size + 3) // 4 * 4 if word_alignment else size
        result = bytes(self.buffer[:size])
        del self.buffer[:consumed]
        return result

    async def _async_recv_channel(self, size, word_alignment=False):
        return self._recv_channel(size, word_alignment)


def vector(value, code=335544569):
    pack = lambda n: struct.pack('!i', n)
    return (pack(isc_arg_gds) + pack(code) + pack(isc_arg_string)
            + pack(len(value)) + value + b'\0' * (-len(value) % 4)
            + pack(isc_arg_end))


class StatusVectorTest(unittest.TestCase):
    def test_sync_and_async_consume_diagnostic(self):
        for value in (b'\xc3', 'méil'.encode()):
            for asynchronous in (False, True):
                with self.subTest(value=value, asynchronous=asynchronous):
                    response = Response(vector(value) + b'NEXT')
                    if asynchronous:
                        result = asyncio.run(response._async_parse_status_vector())
                    else:
                        result = ConnectionResponseMixin._parse_status_vector(response)
                    self.assertIn(335544569, result[0])
                    self.assertEqual(response.buffer, b'NEXT')

    def test_index_key_size_error_is_not_suppressed(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                response = Response(bytes(16) + vector(b'long_index', 335544434) + b'NEXT')
                with self.assertRaises(OperationalError) as caught:
                    if asynchronous:
                        asyncio.run(response._async_parse_op_response())
                    else:
                        response._parse_op_response()
                self.assertIn('key size exceeds', str(caught.exception))
                self.assertIn('long_index', str(caught.exception))
                self.assertEqual(response.buffer, b'NEXT')

    def test_data_decoding_remains_strict(self):
        with self.assertRaises(UnicodeDecodeError):
            Response(b'').bytes_to_str(b'\xc3')
