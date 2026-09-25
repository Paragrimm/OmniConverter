"""One window per user: later launches (e.g. one per file from Explorer) forward their files."""

from __future__ import annotations

import getpass
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    return "omniconverter-" + hashlib.sha1(user.encode()).hexdigest()[:12]


class SingleInstance(QObject):
    files_received = Signal(list)

    def __init__(self, name: str | None = None) -> None:
        super().__init__()
        self.name = name or server_name()
        self._server: QLocalServer | None = None
        self._lock = QLockFile(str(Path(QDir.tempPath()) / f"{self.name}.lock"))
        self._lock.setStaleLockTime(10_000)

    def acquire_or_forward(self, paths: list[str]) -> bool:
        """``True`` if this is the primary instance, ``False`` if *paths* were forwarded."""
        self._lock.tryLock(5_000)  # serialize simultaneous starts
        try:
            if self._forward(paths):
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

    def _forward(self, paths: list[str]) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(_TIMEOUT_MS):
            return False
        socket.write(json.dumps([str(Path(p).resolve()) for p in paths]).encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            self._handle(self._server.nextPendingConnection())

    def _handle(self, socket: QLocalSocket) -> None:
        buffer = bytearray()
        finished = False

        def read() -> None:
            buffer.extend(bytes(socket.readAll()))

        def done() -> None:
            nonlocal finished
            if finished:  # both "disconnected" and the state check below may get here
                return
            finished = True
            read()
            socket.readyRead.disconnect(read)
            socket.disconnected.disconnect(done)
            socket.deleteLater()
            try:
                paths = json.loads(buffer.decode("utf-8") or "[]")
            except ValueError:
                return
            self.files_received.emit([str(p) for p in paths])

        socket.readyRead.connect(read)
        socket.disconnected.connect(done)
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            done()  # the client was quicker than us
