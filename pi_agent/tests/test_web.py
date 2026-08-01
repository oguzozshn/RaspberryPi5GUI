"""Telefon arayuzunun ajandan sunulmasi.

Buradaki asil risk, arayuzu koke ('/') baglamanin mevcut yollari yutmasi: bir
mount, eslesmeyen her yolu ustlenir. Bu yuzden her API yolu ayri ayri
dogrulaniyor - sessizce kirilirlarsa masaustu uygulamasi da telefon da calismaz
hale gelir.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pi_agent.main import WEB_ROOT
from pi_protocol import AuthRequestPayload, Envelope, MessageType

from .conftest import TOKEN


def test_healthz_still_answers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_websocket_still_answers(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
        )
        assert ws.receive_json()["type"] == MessageType.AUTH_OK.value


def test_file_routes_still_answer(client: TestClient) -> None:
    """Token olmadan 401 bekliyoruz - yani istek dosya route'una ulasti,
    statik dosya sunucusuna dusup 404 olmadi."""
    response = client.get("/files/download", params={"path": "/etc/hostname"})
    assert response.status_code == 401


def test_index_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Pi Kontrol" in response.text


def test_assets_are_served(client: TestClient) -> None:
    for path, fragment in (
        ("/app.js", "auth.request"),
        ("/style.css", "--accent"),
        ("/icon.svg", "<svg"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert fragment in response.text, path


def test_manifest_is_valid_json_and_standalone(client: TestClient) -> None:
    """Ana ekrana eklendiginde tarayici cubugu olmadan acilmasi buna bagli."""
    manifest = json.loads(client.get("/manifest.json").text)
    assert manifest["display"] == "standalone"
    assert manifest["icons"], "simge olmadan ana ekran kisayolu cirkin gorunur"


def test_unknown_path_is_a_not_found(client: TestClient) -> None:
    assert client.get("/boyle-bir-sey-yok").status_code == 404


def test_web_root_ships_with_the_package() -> None:
    """Editable kurulumda bile dosyalarin yerinde olmasi gerekiyor; install.sh
    'pip install -e' kullandigi icin bu klasor kaynak agacindan sunuluyor."""
    assert WEB_ROOT.is_dir()
    for name in ("index.html", "app.js", "style.css", "manifest.json", "icon.svg"):
        assert (WEB_ROOT / name).is_file(), name


def test_client_speaks_the_same_protocol_types() -> None:
    """JS istemci mesaj adlarini elle yaziyor; sema degisirse sessizce kirilmasin."""
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    for message_type in (
        MessageType.AUTH_REQUEST,
        MessageType.AUTH_OK,
        MessageType.STATS_UPDATE,
        MessageType.DOCKER_LIST,
        MessageType.DOCKER_ACTION,
        MessageType.POWER_ACTION,
    ):
        assert message_type.value in source, message_type.value
