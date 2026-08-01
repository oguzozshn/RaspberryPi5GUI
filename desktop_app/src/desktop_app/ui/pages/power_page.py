from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import (
    GpioListResultPayload,
    GpioPin,
    GpioReleaseResultPayload,
    GpioWriteResultPayload,
    PowerActionResultPayload,
)

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted

_GPIO_COLUMNS = ["Pin", "BCM", "Mod", "Seviye", "Kullanan", "Normalde"]

_POWER_PROMPTS = {
    "reboot": (
        "Yeniden baslat",
        "{host} yeniden baslatilsin mi?\n\n"
        "Baglanti kesilecek; Pi acildiktan sonra uygulama yeniden baglanmayi dener.",
    ),
    "shutdown": (
        "Kapat",
        "{host} kapatilsin mi?\n\n"
        "DIKKAT: Kapanan Pi'yi uzaktan acmanin yolu yoktur - fiziksel olarak "
        "gucunu kesip yeniden vermeniz gerekir.",
    ),
}


class PowerPage(QWidget):
    """Reboot/shutdown plus a read-write view of the 40-pin header.

    Both halves are one-way doors in different senses: a shutdown cannot be
    undone remotely, and a GPIO write drives real voltage into whatever is
    attached. Every action here is behind an explicit confirmation."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._pins: list[GpioPin] = []

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_power_group())
        layout.addWidget(self._build_gpio_group(), stretch=1)

        app_state.power_action_done.connect(self._on_power_result)
        app_state.gpio_listed.connect(self._on_gpio)
        app_state.gpio_write_done.connect(self._on_gpio_write)
        app_state.gpio_release_done.connect(self._on_gpio_release)

        if app_state.latest_gpio is not None:
            self._on_gpio(app_state.latest_gpio)

    # --- construction -------------------------------------------------------

    def _build_power_group(self) -> QGroupBox:
        group = QGroupBox("Guc")

        # "Kapat" tek basina Turkce'de once "pencereyi kapat" diye okunur; sonucu
        # fiziksel erisim gerektiren bir islem icin fazla belirsiz. Etiketler
        # ozneyi acikca soyluyor, kapatma dugmesi ayrica kirmizi.
        self._reboot_button = QPushButton("Pi'yi Yeniden Baslat")
        self._shutdown_button = QPushButton("Pi'yi Kapat (guc kesilir)")
        self._shutdown_button.setStyleSheet("color: #c0392b; font-weight: bold;")
        self._shutdown_button.setToolTip(
            "Raspberry Pi'yi kapatir. Uzaktan geri acilamaz: kart uzerindeki guc\n"
            "dugmesine basmaniz ya da kabloyu cikarip takmaniz gerekir."
        )
        self._reboot_button.setToolTip("Raspberry Pi'yi yeniden baslatir (~30-60 sn).")
        self._reboot_button.clicked.connect(lambda: self._confirm_power("reboot"))
        self._shutdown_button.clicked.connect(lambda: self._confirm_power("shutdown"))

        buttons = QHBoxLayout()
        buttons.addWidget(self._reboot_button)
        buttons.addWidget(self._shutdown_button)
        buttons.addStretch(1)

        self._power_status = QLabel("")
        self._power_status.setStyleSheet(muted(self, size_px=12))

        inner = QVBoxLayout(group)
        inner.addLayout(buttons)
        inner.addWidget(self._power_status)
        return group

    def _build_gpio_group(self) -> QGroupBox:
        group = QGroupBox("GPIO (40-pin baslik)")

        self._gpio_banner = QLabel("")
        self._gpio_banner.setWordWrap(True)
        self._gpio_banner.setStyleSheet(muted(self, size_px=12))

        self._refresh_button = QPushButton("Yenile")
        self._refresh_button.clicked.connect(self.refresh)
        self._high_button = QPushButton("1 (HIGH) yap")
        self._low_button = QPushButton("0 (LOW) yap")
        self._release_button = QPushButton("Girise al")
        self._release_button.setToolTip(
            "Pini surmeyi birakir ve girise dondurur. Ajani durdurmak bunu yapmaz:\n"
            "surulen bir pin, hat serbest birakilsa da surmeye devam eder."
        )
        self._high_button.clicked.connect(lambda: self._confirm_write(1))
        self._low_button.clicked.connect(lambda: self._confirm_write(0))
        self._release_button.clicked.connect(self._confirm_release)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._refresh_button)
        toolbar.addWidget(self._high_button)
        toolbar.addWidget(self._low_button)
        toolbar.addWidget(self._release_button)
        toolbar.addStretch(1)

        self._table = QTableWidget(0, len(_GPIO_COLUMNS))
        self._table.setHorizontalHeaderLabels(_GPIO_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._gpio_status = QLabel("")
        self._gpio_status.setStyleSheet(muted(self, size_px=12))

        inner = QVBoxLayout(group)
        inner.addWidget(self._gpio_banner)
        inner.addLayout(toolbar)
        inner.addWidget(self._table, stretch=1)
        inner.addWidget(self._gpio_status)

        for button in (self._high_button, self._low_button, self._release_button):
            button.setEnabled(False)
        return group

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        capabilities = self._app_state.capabilities
        if not capabilities.systemd:
            self._reboot_button.setEnabled(False)
            self._shutdown_button.setEnabled(False)
            self._set_power_status("systemd yok — guc kontrolu kullanilamiyor.", warn=True)

        if not capabilities.gpio:
            detail = capabilities.gpio_detail or "sebep bildirilmedi"
            self._gpio_banner.setText(f"GPIO kullanilamiyor: {detail}")
            self._gpio_banner.setStyleSheet("color: #e67e22;")
            self._refresh_button.setEnabled(False)
            return

        self._gpio_banner.setText(
            f"{capabilities.gpio_detail} · Bir pini surmek bagli donanima gercek voltaj "
            "verir; 3.3 V toleransli olmayan bir seye bagliysa zarar verebilir."
        )
        self.refresh()

    def refresh(self) -> None:
        self._set_gpio_status("Pinler okunuyor...")
        schedule(
            self._app_state.request_gpio(),
            lambda exc: self._set_gpio_status(str(exc), warn=True),
        )

    # --- power --------------------------------------------------------------

    def _confirm_power(self, action: str) -> None:
        title, template = _POWER_PROMPTS[action]
        stats = self._app_state.latest_stats
        host = stats.hostname if stats is not None else self._app_state.host

        answer = QMessageBox.question(
            self,
            title,
            template.format(host=host),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._request_power(action)

    def _request_power(self, action: str) -> None:
        verb = "Yeniden baslatma" if action == "reboot" else "Kapatma"
        self._set_power_status(f"{verb} komutu gonderiliyor...")
        schedule(
            self._app_state.power_action(action),
            lambda exc: self._set_power_status(str(exc), warn=True),
        )

    def _on_power_result(self, payload: PowerActionResultPayload) -> None:
        if payload.ok:
            # The agent answers before the Pi finishes going down, so the
            # disconnect that follows in a second or two is expected, not a bug.
            self._set_power_status(
                f"{payload.action}: {payload.detail}. Baglantinin kesilmesi normaldir."
            )
        else:
            self._set_power_status(f"{payload.action} basarisiz: {payload.detail}", warn=True)

    # --- gpio ---------------------------------------------------------------

    def _on_gpio(self, payload: GpioListResultPayload) -> None:
        self._pins = payload.pins
        self._table.setRowCount(len(payload.pins))
        for row, pin in enumerate(payload.pins):
            values = [
                str(pin.physical),
                f"GPIO{pin.bcm}",
                pin.mode,
                "—" if pin.value is None else str(pin.value),
                pin.consumer,
                pin.reserved_for,
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 3 and pin.value == 1:
                    item.setForeground(QBrush(QColor("#27ae60")))
                if column == 3 and pin.value is None:
                    item.setForeground(QBrush(QColor("#7f8c8d")))
                if column == 1 and not pin.writable:
                    item.setToolTip("Bu pine yazma engellidir (HAT ID EEPROM).")
                self._table.setItem(row, column, item)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        unreadable = sum(1 for pin in payload.pins if pin.value is None)
        suffix = f" · {unreadable} pin baska bir surucude" if unreadable else ""
        self._set_gpio_status(f"{len(payload.pins)} pin{suffix}")
        self._on_selection_changed()

    def _on_gpio_write(self, payload: GpioWriteResultPayload) -> None:
        if payload.ok:
            self._set_gpio_status(payload.detail)
            self.refresh()
        else:
            self._set_gpio_status(f"GPIO{payload.bcm} yazilamadi: {payload.detail}", warn=True)

    def _selected_pin(self) -> GpioPin | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        return self._pins[index] if index < len(self._pins) else None

    def _on_selection_changed(self) -> None:
        pin = self._selected_pin()
        enabled = pin is not None and pin.writable
        self._high_button.setEnabled(enabled)
        self._low_button.setEnabled(enabled)
        # Only offer "hand it back" for pins that are actually outputs - on an
        # input pin the button would do nothing visible.
        self._release_button.setEnabled(enabled and pin.mode == "output")

    def _confirm_write(self, value: int) -> None:
        pin = self._selected_pin()
        if pin is None or not pin.writable:
            return

        warning = (
            f"\n\nBu pin normalde {pin.reserved_for} icin kullaniliyor; surmek o "
            "arabirimi bozabilir."
            if pin.reserved_for
            else ""
        )
        answer = QMessageBox.question(
            self,
            "GPIO yaz",
            f"GPIO{pin.bcm} (fiziksel pin {pin.physical}) cikisa alinip {value} "
            f"yapilsin mi?{warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._write(pin.bcm, value)

    def _confirm_release(self) -> None:
        pin = self._selected_pin()
        if pin is None or not pin.writable:
            return

        answer = QMessageBox.question(
            self,
            "Girise al",
            f"GPIO{pin.bcm} (fiziksel pin {pin.physical}) surulmeyi birakip girise "
            "alinsin mi?\n\nPine bagli olan sey (role, LED, surucu...) enerjisiz kalir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._release(pin.bcm)

    def _release(self, bcm: int) -> None:
        self._set_gpio_status(f"GPIO{bcm} girise aliniyor...")
        schedule(
            self._app_state.release_gpio(bcm),
            lambda exc: self._set_gpio_status(str(exc), warn=True),
        )

    def _on_gpio_release(self, payload: GpioReleaseResultPayload) -> None:
        if payload.ok:
            self._set_gpio_status(payload.detail)
            self.refresh()
        else:
            self._set_gpio_status(f"GPIO{payload.bcm} birakilamadi: {payload.detail}", warn=True)

    def _write(self, bcm: int, value: int) -> None:
        self._set_gpio_status(f"GPIO{bcm} <- {value}...")
        schedule(
            self._app_state.write_gpio(bcm, value),
            lambda exc: self._set_gpio_status(str(exc), warn=True),
        )

    # --- status labels ------------------------------------------------------

    def _set_power_status(self, text: str, warn: bool = False) -> None:
        self._power_status.setText(text)
        self._power_status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))

    def _set_gpio_status(self, text: str, warn: bool = False) -> None:
        self._gpio_status.setText(text)
        self._gpio_status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))
