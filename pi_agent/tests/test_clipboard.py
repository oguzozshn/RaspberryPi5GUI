from __future__ import annotations

import asyncio
import sys

import pytest

from pi_agent.handlers import clipboard


def test_detect_returns_none_without_a_graphical_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert clipboard.detect() is None


def test_detect_prefers_wayland_when_socket_exists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / "wayland-0").write_text("")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")

    tool = clipboard.detect()
    assert tool is not None and tool.write_cmd == ["wl-copy"]


def test_detect_falls_back_to_x11_when_wayland_socket_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # WAYLAND_DISPLAY is set by the unit file unconditionally, so a missing
    # socket is the normal signal that the session is X11 (or absent).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")

    tool = clipboard.detect()
    assert tool is not None and tool.write_cmd[0] == "xclip"


def test_detect_returns_none_when_tools_are_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    (tmp_path / "wayland-0").write_text("")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)

    assert clipboard.detect() is None
    assert "kurulu degil" in clipboard.describe()


@pytest.mark.asyncio
async def test_write_text_reports_failure_without_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard, "detect", lambda: None)
    ok, detail = await clipboard.write_text("gizli-sifre")
    assert ok is False
    assert detail


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess pipeline")
async def test_write_text_round_trips_through_a_stub_tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Exercise the real subprocess path with `tee` standing in for wl-copy."""
    sink = tmp_path / "clip.txt"
    monkeypatch.setattr(
        clipboard,
        "detect",
        lambda: clipboard.ClipboardTool("stub", ["tee", str(sink)], ["cat", str(sink)]),
    )

    ok, _ = await clipboard.write_text("gizli-sifre")
    assert ok and sink.read_text() == "gizli-sifre"

    ok, text = await clipboard.read_text()
    assert ok and text == "gizli-sifre"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess pipeline")
async def test_write_text_succeeds_when_the_tool_leaves_a_daemon_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression, found on a real Pi 5.

    wl-copy (and xclip) fork a helper that keeps serving the selection and
    inherits our pipes. Waiting for pipe EOF meant a successful copy was
    reported as a timeout - the text was on the clipboard, the UI said it had
    failed. The stub below reproduces that: the shell exits immediately but
    leaves a background process holding the descriptors.
    """
    sink = tmp_path / "clip.txt"
    monkeypatch.setattr(
        clipboard,
        "detect",
        lambda: clipboard.ClipboardTool(
            "stub-daemon", ["sh", "-c", f"cat > {sink}; sleep 15 &"], ["cat", str(sink)]
        ),
    )

    ok, detail = await asyncio.wait_for(clipboard.write_text("gizli-sifre"), timeout=10)
    assert ok, detail
    assert sink.read_text() == "gizli-sifre"
