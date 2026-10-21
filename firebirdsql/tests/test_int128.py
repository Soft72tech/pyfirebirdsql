import random
import unittest
from decimal import Decimal

from firebirdsql.consts import SQL_TYPE_INT128
from firebirdsql.utils import bytes_to_bint
from firebirdsql.xsqlvar import XSQLVAR


class Int128Test(unittest.TestCase):
    def test_signed_low_word_does_not_sign_extend(self):
        values = [0, 1, -1, 2**63, 2**64 - 1, 2**64, -(2**64),
                  2**127 - 1, -(2**127), 3 * 10**33, -(3 * 10**33)]
        rng = random.Random(42)
        values += [rng.randrange(-(2**127), 2**127) for _ in range(100)]
        for value in values:
            with self.subTest(value=value):
                raw = value.to_bytes(16, 'big', signed=True)
                self.assertEqual(bytes_to_bint(raw), value)
                self.assertEqual(bytes_to_bint(raw, u=True), value % (2**128))

    def test_scaled_int128(self):
        variable = object.__new__(XSQLVAR)
        variable.sqltype = SQL_TYPE_INT128
        variable.sqlscale = -4
        value = 2**63 + 1234
        self.assertEqual(variable.value(value.to_bytes(16, 'big', signed=True)),
                         Decimal(value).scaleb(-4))
