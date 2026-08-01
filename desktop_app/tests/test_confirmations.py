"""Onay diyalogu gerektiren her eylemin gercekten tetiklendigini dogrular.

Gercek bir Pi'de yakalandi: 'Pi'yi Kapat'a basip onaylayinca hicbir sey
olmuyordu. Sebep, QMessageBox.question()'in bu PySide6 surumunde enum uyesi
degil duz int dondurmesi (Yes = 16384) ve kodun `is not` ile kimlik
karsilastirmasi yapmasiydi - yani onay her zaman iptale cevriliyordu.

Onceki testler sayfalarin ic metotlarini (_request_power gibi) dogrudan
cagirdigi icin diyalogu hic gecmiyor ve bunu goremiyordu. Buradaki testler
diyalogun donus degerini uretimdekiyle ayni tipte taklit eder.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from pi_protocol import GpioListResultPayload, GpioPin, ProcessInfo, ProcessListResultPayload

from desktop_app.app_state import AppState
from desktop_app.ui.pages import dashboard_page as dashboard_module
from desktop_app.ui.pages import power_page as power_module
from desktop_app.ui.pages.dashboard_page import DashboardPage
from desktop_app.ui.pages.power_page import PowerPage

# Diyalogun gercekte dondurdugu sey: enum uyesi degil, duz int.
YES = int(QMessageBox.StandardButton.Yes)
NO = int(QMessageBox.StandardButton.No)


def _answer(monkeypatch: pytest.MonkeyPatch, module, value: int) -> None:
    monkeypatch.setattr(module.QMessageBox, "question", staticmethod(lambda *a, **k: value))


def _spy(monkeypatch: pytest.MonkeyPatch, app_state: AppState, name: str) -> list[tuple]:
    """AppState'in giden cagrisini yakalar.

    Kayit, coroutine olusturulurken yapilir - calistirilirken degil: testlerde
    calisan bir event loop yok, schedule() coroutine'i baslatamadan birakiyor.
    """
    calls: list[tuple] = []

    def fake(*args, **kwargs):
        calls.append(args)

        async def noop() -> None:
            return None

        return noop()

    monkeypatch.setattr(app_state, name, fake)
    return calls


def _gpio_page(app_state: AppState) -> PowerPage:
    page = PowerPage(app_state)
    page._on_gpio(
        GpioListResultPayload(
            pins=[
                GpioPin(bcm=17, physical=11, mode="output", value=1),
                GpioPin(bcm=4, physical=7, mode="input", value=0),
            ]
        )
    )
    return page


# --- guc --------------------------------------------------------------------


def test_confirming_shutdown_actually_sends_it(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = PowerPage(app_state)
    calls = _spy(monkeypatch, app_state, "power_action")
    _answer(monkeypatch, power_module, YES)

    page._confirm_power("shutdown")
    assert calls == [("shutdown",)]


def test_confirming_reboot_actually_sends_it(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = PowerPage(app_state)
    calls = _spy(monkeypatch, app_state, "power_action")
    _answer(monkeypatch, power_module, YES)

    page._confirm_power("reboot")
    assert calls == [("reboot",)]


def test_declining_shutdown_sends_nothing(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = PowerPage(app_state)
    calls = _spy(monkeypatch, app_state, "power_action")
    _answer(monkeypatch, power_module, NO)

    page._confirm_power("shutdown")
    assert calls == [], "iptal edilen onay komut gondermemeli"


# --- gpio -------------------------------------------------------------------


def test_confirming_a_gpio_write_sends_it(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _gpio_page(app_state)
    page._table.selectRow(0)
    calls = _spy(monkeypatch, app_state, "write_gpio")
    _answer(monkeypatch, power_module, YES)

    page._confirm_write(1)
    assert calls == [(17, 1)]


def test_declining_a_gpio_write_sends_nothing(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _gpio_page(app_state)
    page._table.selectRow(0)
    calls = _spy(monkeypatch, app_state, "write_gpio")
    _answer(monkeypatch, power_module, NO)

    page._confirm_write(1)
    assert calls == []


def test_confirming_a_release_sends_it(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _gpio_page(app_state)
    page._table.selectRow(0)
    calls = _spy(monkeypatch, app_state, "release_gpio")
    _answer(monkeypatch, power_module, YES)

    page._confirm_release()
    assert calls == [(17,)]


# --- process sonlandirma ----------------------------------------------------


def test_confirming_a_kill_sends_it(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = DashboardPage(app_state)
    page._process_table.update_processes(
        ProcessListResultPayload(
            total_count=1,
            processes=[
                ProcessInfo(pid=4242, name="python", cpu_percent=1.0, memory_percent=1.0,
                            memory_rss_bytes=1024, status="running", cmdline="python x.py")
            ],
        )
    )
    page._process_table.selectRow(0)
    calls = _spy(monkeypatch, app_state, "kill_process")
    _answer(monkeypatch, dashboard_module, YES)

    page._kill_selected()
    assert calls == [(4242,)]
