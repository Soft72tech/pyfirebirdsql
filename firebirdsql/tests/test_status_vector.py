"""Malformed diagnostic text must not leave the wire response unread."""
import asyncio
import struct
import unittest

from firebirdsql.consts import isc_arg_end, isc_arg_gds, isc_arg_string
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


def vector(value):
    pack = lambda n: struct.pack('!i', n)
    return (pack(isc_arg_gds) + pack(335544569) + pack(isc_arg_string)
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

    def test_data_decoding_remains_strict(self):
        with self.assertRaises(UnicodeDecodeError):
            Response(b'').bytes_to_str(b'\xc3')
