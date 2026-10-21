"""Both optional PyCryptodome and bundled ciphers accept keyword construction."""
from firebirdsql.chacha import ChaCha20 as BundledChaCha20


def test_bundled_chacha_keyword_factory():
    cipher = BundledChaCha20.new(key=b'k' * 32, nonce=b'n' * 12)
    assert len(cipher.encrypt(b'probe')) == 5


def test_async_chacha_keyword_factory():
    from firebirdsql.aio.fbcore import ChaCha20
    cipher = ChaCha20.new(key=b'k' * 32, nonce=b'n' * 12)
    assert len(cipher.encrypt(b'probe')) == 5
