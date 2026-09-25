"""One window per user: later launches (e.g. one per file from Explorer) forward their files.

Protocol: the client sends one JSON line with the paths and waits for ``ok`` before it
disconnects, so no data is lost when the pipe is closed (Windows named pipes).
"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_TIMEOUT_MS = 3000
_ACK = b"ok\n"


def server_name() -> str:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    return "omniconverter-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def forward(name: str, paths: list[str]) -> bool:
    """Send *paths* to a running instance. ``False`` if there is none."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_TIMEOUT_MS):
        return False
    payload = json.dumps([str(Path(p).resolve()) for p in paths]) + "\n"
    socket.write(payload.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(_TIMEOUT_MS)
    socket.waitForReadyRead(_TIMEOUT_MS)  # the "ok" – the primary has the data now
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(_TIMEOUT_MS)
    return True


class SingleInstance(QObject):
    files_received = Signal(list)

    def __init__(self, name: str | None = None) -> None:
        super().__init__()
        self.name = name or server_name()
        self._server: QLocalServer | None = None
        self._sockets: dict[QLocalSocket, tuple] = {}
        self._lock = QLockFile(str(Path(QDir.tempPath()) / f"{self.name}.lock"))
        self._lock.setStaleLockTime(10_000)

    def acquire_or_forward(self, paths: list[str]) -> bool:
        """``True`` if this is the primary instance, ``False`` if *paths* were forwarded."""
        self._lock.tryLock(5_000)  # serialize simultaneous starts
        try:
            if forward(self.name, paths):
                return False
            QLocalServer.removeServer(self.name)  # stale socket after a crash
            server = QLocalServer(self)
            server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            if server.listen(self.name):
                server.newConnection.connect(self._on_connection)
                self._server = server
            return True
        finally:
            self._lock.unlock()

    def close(self) -> None:
        """Stop listening and drop open connections (call before the app quits)."""
        for socket in list(self._sockets):
            self._release(socket)
            socket.abort()
        if self._server is not None:
            self._server.close()
            self._server = None

    def _release(self, socket: QLocalSocket) -> None:
        # Detach our Python callbacks first: Qt may emit signals while destroying the socket.
        for signal, slot in self._sockets.pop(socket, ()):
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)
        socket.deleteLater()

    def _on_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            self._handle(self._server.nextPendingConnection())

    def _handle(self, socket: QLocalSocket) -> None:
        buffer = bytearray()
        finished = False

        def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            line = bytes(buffer).split(b"\n", 1)[0]
            if socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
                socket.write(_ACK)
                socket.flush()
                socket.disconnectFromServer()  # after the ack has been written
            try:
                paths = json.loads(line.decode("utf-8") or "[]")
            except ValueError:
                return
            self.files_received.emit([str(p) for p in paths])

        def read() -> None:
            buffer.extend(bytes(socket.readAll()))
            if b"\n" in buffer:
                finish()

        def closed() -> None:
            if socket not in self._sockets:
                return
            buffer.extend(bytes(socket.readAll()))
            finish()
            self._release(socket)

        socket.readyRead.connect(read)
        socket.disconnected.connect(closed)
        self._sockets[socket] = ((socket.readyRead, read), (socket.disconnected, closed))
        if socket.bytesAvailable():
            read()
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            closed()
