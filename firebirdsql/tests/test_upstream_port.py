"""Database-free regression checks for fixes adapted to upstream APIs."""
import asyncio
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from firebirdsql.fbcore import Transaction, Cursor
from firebirdsql.aio.fbcore import AsyncTransaction, AsyncConnection, AsyncCursor, AsyncStatement
from firebirdsql.err import OperationalError


class PortTest(unittest.TestCase):
    def transaction(self, asynchronous):
        cls = AsyncTransaction if asynchronous else Transaction
        trans = object.__new__(cls)
        cursor = Mock()
        cursor.close = AsyncMock() if asynchronous else Mock()
        conn = SimpleNamespace(db_handle=1, _cursors={trans: weakref.WeakSet([cursor])},
            _op_commit=Mock(), _op_rollback=Mock(), _op_commit_retaining=Mock(),
            _op_rollback_retaining=Mock(), _op_exec_immediate=Mock(),
            _op_response=Mock(return_value=(0, 0, b'')),
            _async_op_response=AsyncMock(return_value=(0, 0, b'')))
        # Real close removes the cursor from the registry.
        cursor.close.side_effect = lambda: conn._cursors[trans].discard(cursor)
        trans._connection = conn
        trans._trans_handle = 42
        trans.is_dirty = False
        return trans, cursor, conn

    def test_readonly_boundaries_close_cursors_and_keep_weaksets(self):
        for asynchronous in (False, True):
            for method in ('commit', 'rollback', 'close'):
                with self.subTest(asynchronous=asynchronous, method=method):
                    trans, cursor, conn = self.transaction(asynchronous)
                    result = getattr(trans, method)()
                    if asynchronous:
                        asyncio.run(result)
                        cursor.close.assert_awaited_once_with()
                    else:
                        cursor.close.assert_called_once_with()
                    self.assertIsNone(trans._trans_handle)
                    self.assertIsInstance(conn._cursors[trans], weakref.WeakSet)
                    self.assertFalse(conn._cursors[trans])

    def test_retaining_and_savepoints_preserve_cursors(self):
        for asynchronous in (False, True):
            for method, kwargs in [('commit', {'retaining': True}),
                                   ('rollback', {'retaining': True}),
                                   ('rollback', {'savepoint': 's'})]:
                trans, cursor, conn = self.transaction(asynchronous)
                result = getattr(trans, method)(**kwargs)
                if asynchronous:
                    asyncio.run(result)
                cursor.close.assert_not_called()
                self.assertEqual(trans._trans_handle, 42)

    def connection(self):
        conn = object.__new__(AsyncConnection)
        conn.sock = Mock()
        conn.db_handle = 1
        conn._transaction = None
        conn._cursors = {}
        conn.is_services = False
        conn._op_detach = Mock()
        conn._async_op_response = AsyncMock(return_value=(0, 0, b''))
        return conn

    def test_close_cleans_transport_after_detach_failure(self):
        conn = self.connection()
        sock = conn.sock
        conn._async_op_response.side_effect = OperationalError('detach failed')
        with self.assertRaises(OperationalError):
            asyncio.run(conn.aclose())
        sock.close.assert_called_once_with()
        self.assertIsNone(conn.sock)
        self.assertIsNone(conn.db_handle)

    def test_context_exit_closes_after_commit_failure(self):
        conn = self.connection()
        conn.commit = AsyncMock(side_effect=ValueError('commit failed'))
        conn.close = AsyncMock()
        with self.assertRaises(ValueError):
            asyncio.run(conn.__aexit__(None, None, None))
        conn.close.assert_awaited_once_with()
        conn.terminate()

    def test_receive_cancellation_timeout_and_eof_discard_transport(self):
        for error in (asyncio.CancelledError(), asyncio.TimeoutError(), OSError('broken'), None):
            conn = self.connection()
            conn.timeout = None
            sock = conn.sock
            sock.async_recv = AsyncMock(side_effect=error, return_value=b'')
            expected = asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else OperationalError
            with self.assertRaises(expected):
                asyncio.run(conn._async_recv_channel(4))
            self.assertIsNone(conn.sock)
            sock.close.assert_called_once_with()

    def test_async_drop_releases_unopened_statement(self):
        stmt = object.__new__(AsyncStatement)
        conn = Mock(accept_type=0)
        conn._async_op_response = AsyncMock(return_value=(0, 0, b''))
        stmt.trans = SimpleNamespace(connection=conn)
        stmt.handle = 42
        stmt._is_open = False
        asyncio.run(stmt.drop())
        conn._op_free_statement.assert_called_once()
        self.assertEqual(stmt.handle, -1)

    def test_rowcount_alias_uses_upstream_async_counter(self):
        cursor = object.__new__(AsyncCursor)
        cursor._rowcount = AsyncMock(return_value=7)
        self.assertEqual(asyncio.run(cursor.get_rowcount()), 7)
        self.assertEqual(cursor.rowcount, 7)
        cursor._rowcount.assert_awaited_once_with()

    def test_upstream_socket_receive_is_nonblocking(self):
        import socket
        from firebirdsql.aio.stream import AsyncSocketStream

        async def run():
            reader, writer = socket.socketpair()
            reader.setblocking(False)
            stream = object.__new__(AsyncSocketStream)
            stream._sock = reader
            stream.loop = asyncio.get_running_loop()
            stream.read_translator = None
            stream._last_send_task = None
            stream._decompressor = None
            stream._buf = b''
            try:
                task = asyncio.create_task(stream.async_recv(1))
                await asyncio.sleep(0.01)
                self.assertFalse(task.done())
                writer.send(b'x')
                self.assertEqual(await asyncio.wait_for(task, 1), b'x')
                self.assertFalse(reader.getblocking())
            finally:
                reader.close()
                writer.close()
        asyncio.run(run())

    def test_async_empty_description(self):
        cursor = object.__new__(AsyncCursor)
        cursor.stmt = SimpleNamespace(xsqlda=[])
        self.assertIsNone(cursor.description)
