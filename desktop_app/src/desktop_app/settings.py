from __future__ import annotations

import keyring
from PySide6.QtCore import QSettings

_KEYRING_SERVICE = "RasperryPi5GUI"
_KEYRING_USERNAME = "pairing_token"


class Settings:
    """Non-secret connection fields via QSettings; the pairing token via Windows
    Credential Manager (keyring) so it never sits in a plaintext ini file."""

    def __init__(self) -> None:
        self._qsettings = QSettings("RasperryPi5GUI", "DesktopApp")

    @property
    def host(self) -> str:
        return str(self._qsettings.value("connection/host", ""))

    @host.setter
    def host(self, value: str) -> None:
        self._qsettings.setValue("connection/host", value)

    @property
    def port(self) -> int:
        return int(self._qsettings.value("connection/port", 8765))

    @port.setter
    def port(self, value: int) -> None:
        self._qsettings.setValue("connection/port", value)

    @property
    def token(self) -> str | None:
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)

    @token.setter
    def token(self, value: str) -> None:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, value)

    def has_saved_connection(self) -> bool:
        return bool(self.host) and self.token is not None
