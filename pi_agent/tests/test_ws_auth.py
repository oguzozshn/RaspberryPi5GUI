from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pi_protocol import AuthRequestPayload, Envelope, MessageType

from .conftest import TOKEN


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ws_auth_ok(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        envelope = Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN))
        ws.send_json(envelope.model_dump(mode="json"))
        reply = ws.receive_json()
        assert reply["type"] == MessageType.AUTH_OK.value


def test_ws_auth_rejected(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        envelope = Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token="wrong-token"))
        ws.send_json(envelope.model_dump(mode="json"))
        reply = ws.receive_json()
        assert reply["type"] == MessageType.AUTH_REJECTED.value


def test_ws_first_message_must_be_auth(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": MessageType.ERROR.value, "id": "x", "ts": 0, "payload": {"code": "c", "message": "m"}})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
