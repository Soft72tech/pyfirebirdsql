"""Exact Decimal parameter encoding, independent of a live server."""
import unittest
from decimal import Decimal, localcontext

from firebirdsql.consts import PROTOCOL_VERSION12, PROTOCOL_VERSION17
from firebirdsql.wireprotocol import WireProtocol


class DecimalParameterTest(unittest.TestCase):
    def encode(self, value, protocol=PROTOCOL_VERSION17):
        wire = WireProtocol()
        wire.accept_version = protocol
        return wire.params_to_blr(0, [value])

    def test_large_coefficients_use_exact_text(self):
        values = ['319438950232418390.273596', '31943874831932418390.01',
                  str(2**63), str(-(2**63) - 1), '9' * 38,
                  '-' + '9' * 38, '1E-129', '1E+128']
        for protocol in (PROTOCOL_VERSION12, PROTOCOL_VERSION17):
            for value in values:
                with self.subTest(protocol=protocol, value=value):
                    with localcontext() as context:
                        context.prec = 6
                        blr, data = self.encode(Decimal(value), protocol)
                    raw = str(Decimal(value)).encode('ascii')
                    length = len(raw)
                    self.assertEqual(blr[6:9], bytes([14, length & 255, length >> 8]))
                    expected = raw + b'\0' * ((4 - length) & 3)
                    expected = (expected + b'\0' * 4 if protocol == PROTOCOL_VERSION12
                                else b'\0' * 4 + expected)
                    self.assertEqual(data, expected)

    def test_int64_boundaries_keep_scaled_binary_format(self):
        for value, coefficient, scale in [
            ('9223372036854775807', 2**63 - 1, 0),
            ('-9223372036854775808', -(2**63), 0),
            ('87673.594069654243', 87673594069654243, -12),
            ('1.000', 1000, -3), ('0', 0, 0),
            ('1E-128', 1, -128), ('1E+127', 1, 127),
        ]:
            with self.subTest(value=value):
                blr, data = self.encode(Decimal(value))
                self.assertEqual(blr[6:8], bytes([16, scale & 255]))
                self.assertEqual(data, b'\0' * 4 + coefficient.to_bytes(8, 'big', signed=True))

    def test_float_exponent_outside_signed_scale_uses_text(self):
        blr, data = self.encode(1.2345678901234567e200)
        self.assertEqual(blr[6], 14)
        self.assertEqual(data[4:].rstrip(b'\0'), b'1.2345678901234567E+200')
