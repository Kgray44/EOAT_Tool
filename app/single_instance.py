from __future__ import annotations

try:
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
except ImportError:  # pragma: no cover
    QLocalServer = QLocalSocket = None


class SingleInstanceGuard:
    """Small Qt local-server guard for one dashboard instance per Windows user session."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.server = None

    def acquire(self) -> bool:
        if QLocalServer is None or QLocalSocket is None:  # pragma: no cover
            return True
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if socket.waitForConnected(150):
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer()
        return self.server.listen(self.server_name)

    def release(self) -> None:
        if self.server is not None:
            self.server.close()
            QLocalServer.removeServer(self.server_name)
            self.server = None
