from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pi_agent.handlers import files
from pi_protocol import (
    AuthRequestPayload,
    Envelope,
    FilesCreatePayload,
    FilesDeletePayload,
    MessageType,
)

from .conftest import TOKEN


def _authenticated(client: TestClient):
    ws = client.websocket_connect("/ws").__enter__()
    ws.send_json(
        Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
    )
    assert ws.receive_json()["type"] == MessageType.AUTH_OK.value
    return ws


# --- create -----------------------------------------------------------------


def test_create_makes_a_file_and_a_directory(tmp_path: Path) -> None:
    ok, detail = files.create(tmp_path / "notlar.txt", is_dir=False)
    assert ok, detail
    assert (tmp_path / "notlar.txt").is_file()

    ok, detail = files.create(tmp_path / "yedek", is_dir=True)
    assert ok, detail
    assert (tmp_path / "yedek").is_dir()


def test_create_never_truncates_an_existing_file(tmp_path: Path) -> None:
    """Ayni adi ikinci kez olusturmak, icerigi silmek anlamina gelmemeli."""
    target = tmp_path / "veri.txt"
    target.write_text("onemli")

    ok, detail = files.create(target, is_dir=False)
    assert not ok
    assert "zaten var" in detail
    assert target.read_text() == "onemli"


def test_create_reports_a_missing_parent(tmp_path: Path) -> None:
    ok, detail = files.create(tmp_path / "yok" / "dosya.txt", is_dir=False)
    assert not ok
    assert "ust dizin" in detail


# --- delete -----------------------------------------------------------------


def test_delete_removes_a_file(tmp_path: Path) -> None:
    target = tmp_path / "gecici.txt"
    target.write_text("x")

    ok, detail = files.delete(target, recursive=False)
    assert ok, detail
    assert not target.exists()


def test_delete_refuses_a_non_empty_directory_without_recursive(tmp_path: Path) -> None:
    folder = tmp_path / "dolu"
    folder.mkdir()
    (folder / "icerik.txt").write_text("x")

    ok, detail = files.delete(folder, recursive=False)
    assert not ok
    assert "bos degil" in detail
    assert (folder / "icerik.txt").exists()


def test_delete_removes_a_tree_when_asked(tmp_path: Path) -> None:
    folder = tmp_path / "dolu"
    (folder / "alt").mkdir(parents=True)
    (folder / "alt" / "icerik.txt").write_text("x")

    ok, detail = files.delete(folder, recursive=True)
    assert ok, detail
    assert not folder.exists()


def test_delete_reports_a_missing_path(tmp_path: Path) -> None:
    ok, detail = files.delete(tmp_path / "yok", recursive=False)
    assert not ok
    assert "bulunamadi" in detail


@pytest.mark.parametrize("path", ["/", "/etc", "/boot", "/home", "/usr"])
def test_delete_refuses_protected_paths(path: str) -> None:
    """Ajan bunlari silebilecek yetkiye sahip; bir dosya tarayicisinin bu
    secenegi sunmasi icin hicbir sebep yok."""
    ok, detail = files.delete(Path(path), recursive=True)
    assert not ok
    assert "korunan yol" in detail


# --- over the wire ----------------------------------------------------------


def test_create_and_delete_round_trip(client: TestClient, tmp_path: Path) -> None:
    ws = _authenticated(client)
    target = str(tmp_path / "yeni.txt")

    ws.send_json(
        Envelope(type=MessageType.FILES_CREATE, payload=FilesCreatePayload(path=target)).model_dump(mode="json")
    )
    reply = ws.receive_json()
    assert reply["type"] == MessageType.FILES_CREATE_RESULT.value
    assert reply["payload"]["ok"] is True
    assert Path(target).is_file()

    ws.send_json(
        Envelope(type=MessageType.FILES_DELETE, payload=FilesDeletePayload(path=target)).model_dump(mode="json")
    )
    reply = ws.receive_json()
    assert reply["type"] == MessageType.FILES_DELETE_RESULT.value
    assert reply["payload"]["ok"] is True
    assert not Path(target).exists()
