from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_upload_download_roundtrip_preserves_bytes(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    payload = os.urandom(3 * 1024 * 1024)  # 3 MB, spans multiple stream chunks
    target = tmp_path / "blob.bin"

    upload = client.put(f"/files/upload?path={target}", content=payload, headers=auth_headers)
    assert upload.status_code == 200
    assert upload.json()["size_bytes"] == len(payload)

    download = client.get(f"/files/download?path={target}", headers=auth_headers)
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == hashlib.sha256(payload).hexdigest()


def test_upload_leaves_no_part_file(client: TestClient, auth_headers: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    client.put(f"/files/upload?path={target}", content=b"data", headers=auth_headers)
    assert target.exists()
    assert not (tmp_path / "x.txt.part").exists()


def test_upload_requires_token(client: TestClient, tmp_path: Path) -> None:
    response = client.put(f"/files/upload?path={tmp_path / 'nope.txt'}", content=b"x")
    assert response.status_code == 401


def test_upload_rejects_wrong_token(client: TestClient, tmp_path: Path) -> None:
    response = client.put(
        f"/files/upload?path={tmp_path / 'nope.txt'}",
        content=b"x",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 403


def test_upload_to_missing_directory_is_404(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    response = client.put(
        f"/files/upload?path={tmp_path / 'yok' / 'a.txt'}", content=b"x", headers=auth_headers
    )
    assert response.status_code == 404


def test_download_missing_file_is_404(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    response = client.get(f"/files/download?path={tmp_path / 'yok.txt'}", headers=auth_headers)
    assert response.status_code == 404


def test_download_directory_is_400(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    response = client.get(f"/files/download?path={tmp_path}", headers=auth_headers)
    assert response.status_code == 400
