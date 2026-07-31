from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import ProcessKillResultPayload, StatsUpdatePayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.format import bytes_human, duration_human
from desktop_app.ui.theme import muted
from desktop_app.ui.widgets.process_table import ProcessTable
from desktop_app.ui.widgets.stat_tile import StatTile

PROCESS_REFRESH_MS = 3000


class DashboardPage(QWidget):
    """Live system metrics. Stats arrive as unsolicited pushes from the agent;
    the process list is polled on a timer because it is far more expensive to
    collect and only matters while this page is on screen."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state

        self._header = QLabel("—")
        self._header.setStyleSheet(muted(self, size_px=13))
        self._processes_in_flight = False

        self._cpu_tile = StatTile("CPU Kullanimi")
        self._temp_tile = StatTile("CPU Sicakligi")
        self._memory_tile = StatTile("Bellek")
        self._disk_tile = StatTile("Disk (/)")

        tiles = QGridLayout()
        for column, tile in enumerate((self._cpu_tile, self._temp_tile, self._memory_tile, self._disk_tile)):
            tiles.addWidget(tile, 0, column)

        self._process_table = ProcessTable()
        self._process_table.itemSelectionChanged.connect(self._on_process_selection)

        self._kill_button = QPushButton("Sonlandir")
        self._kill_button.setEnabled(False)
        self._kill_button.clicked.connect(self._kill_selected)
        self._process_status = QLabel("")
        self._process_status.setStyleSheet(muted(self, size_px=12))

        process_bar = QHBoxLayout()
        process_bar.addWidget(QLabel("Calisan uygulamalar (CPU'ya gore siralanmis)"))
        process_bar.addStretch(1)
        process_bar.addWidget(self._process_status)
        process_bar.addWidget(self._kill_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addLayout(tiles)
        layout.addLayout(process_bar)
        layout.addWidget(self._process_table, stretch=1)

        app_state.stats_updated.connect(self._on_stats)
        app_state.processes_updated.connect(self._on_processes)
        app_state.process_killed.connect(self._on_process_killed)

        if app_state.latest_stats is not None:
            self._on_stats(app_state.latest_stats)
        if app_state.latest_processes is not None:
            self._process_table.update_processes(app_state.latest_processes)

        self._timer = QTimer(self)
        self._timer.setInterval(PROCESS_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_processes)

    def start(self) -> None:
        """Begin polling. Kept out of __init__ so constructing the widget does
        no I/O and does not require a running event loop."""
        self._timer.start()
        self._refresh_processes()

    def _refresh_processes(self) -> None:
        # Collecting the process list takes a noticeable fraction of a second, so
        # skip a tick rather than stacking up requests the agent must work through.
        if not self.isVisible() or self._processes_in_flight:
            return
        self._processes_in_flight = True
        schedule(
            self._app_state.request_processes(),
            lambda _exc: setattr(self, "_processes_in_flight", False),
        )

    def _on_processes(self, payload) -> None:
        self._processes_in_flight = False
        self._process_table.update_processes(payload)

    # --- process termination ------------------------------------------------

    def _on_process_selection(self) -> None:
        self._kill_button.setEnabled(self._process_table.selected_pid() is not None)

    def _kill_selected(self) -> None:
        pid = self._process_table.selected_pid()
        if pid is None:
            return
        name = self._process_table.selected_name() or "?"

        answer = QMessageBox.question(
            self,
            "Process sonlandir",
            f"{name} (PID {pid}) sonlandirilsin mi?\n\n"
            "Once SIGTERM gonderilir; kaydedilmemis veriler kaybolabilir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        self._process_status.setText(f"PID {pid} sonlandiriliyor...")
        schedule(
            self._app_state.kill_process(pid),
            lambda exc: self._process_status.setText(str(exc)),
        )

    def _on_process_killed(self, payload: ProcessKillResultPayload) -> None:
        self._process_status.setText(payload.detail)
        if payload.ok:
            self._refresh_processes()

    def _on_stats(self, stats: StatsUpdatePayload) -> None:
        load = (
            " · yuk " + ", ".join(f"{v:.2f}" for v in stats.load_avg) if stats.load_avg else ""
        )
        self._header.setText(
            f"{stats.hostname} · calisma suresi {duration_human(stats.uptime_seconds)}{load}"
        )

        frequency = f" · {stats.cpu.frequency_mhz:.0f} MHz" if stats.cpu.frequency_mhz else ""
        self._cpu_tile.update_values(
            f"{stats.cpu.percent:.1f} %",
            stats.cpu.percent,
            f"{len(stats.cpu.per_core)} cekirdek{frequency}",
        )

        if stats.cpu.temperature_c is None:
            self._temp_tile.update_values("—", 0, "sensor okunamadi")
        else:
            # Pi 5 starts throttling around 80-85 °C, so scale the bar against that.
            self._temp_tile.update_values(
                f"{stats.cpu.temperature_c:.1f} °C",
                stats.cpu.temperature_c / 85 * 100,
                "throttle esigi ~85 °C",
            )

        self._memory_tile.update_values(
            f"{stats.memory.percent:.1f} %",
            stats.memory.percent,
            f"{bytes_human(stats.memory.used_bytes)} / {bytes_human(stats.memory.total_bytes)}",
        )

        root = next((d for d in stats.disks if d.mountpoint in ("/", "C:\\")), None)
        if root is None and stats.disks:
            root = stats.disks[0]
        if root is not None:
            self._disk_tile.update_values(
                f"{root.percent:.1f} %",
                root.percent,
                f"{bytes_human(root.used_bytes)} / {bytes_human(root.total_bytes)} ({root.mountpoint})",
            )
