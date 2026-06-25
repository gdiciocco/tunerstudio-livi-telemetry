from __future__ import annotations

import json
from typing import Any, Protocol


class Emitter(Protocol):
    def connect(self) -> None:
        ...

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        ...

    def close(self) -> None:
        ...


class DryRunEmitter:
    def connect(self) -> None:
        return None

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        print(json.dumps({"event": event, "payload": payload}, separators=(",", ":"), sort_keys=True), flush=True)

    def close(self) -> None:
        return None


class SocketIoEmitter:
    def __init__(self, url: str) -> None:
        self.url = self._normalize_url(url)
        self._client = None

    def connect(self) -> None:
        try:
            import socketio
        except ImportError as exc:
            raise RuntimeError("Install python-socketio[client] or run with --dry-run") from exc

        self._client = socketio.Client(reconnection=True)
        self._client.connect(self.url, transports=["websocket", "polling"])

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._client is None:
            raise RuntimeError("Socket.IO client is not connected")
        self._client.emit(event, payload)

    def close(self) -> None:
        if self._client is not None:
            self._client.disconnect()

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith("ws://"):
            return "http://" + url[len("ws://") :]
        if url.startswith("wss://"):
            return "https://" + url[len("wss://") :]
        return url

