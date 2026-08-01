"""Masaustu uygulamasini tek dosyalik bir .exe olarak paketler.

Kullanim (masaustu venv'inden):
    .venv-desktop\\Scripts\\python.exe desktop_app\\scripts\\build_exe.py

Sonuc: dist/PiKontrol.exe - Python kurulu olmayan bir Windows'ta da calisir.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
ICON_SVG = ROOT / "pi_agent" / "web" / "icon.svg"
ICON_ICO = BUILD_DIR / "PiKontrol.ico"

# keyring arka uclarini eklentiyle bulur, PyInstaller'in statik analizi goremez:
# eksik olursa uygulama token'i okuyamadigi icin her acilista kurulum ekrani
# gosterir. qasync ve pyte de dinamik import zincirlerinde kayboluyor.
HIDDEN_IMPORTS = (
    "keyring.backends.Windows",
    "keyring.backends.chainer",
    "keyring.backends.fail",
    "qasync",
    "pyte",
)

# PySide6 kocaman: kullanmadigimiz moduller ~150 MB'a mal oluyor.
EXCLUDES = (
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtBluetooth",
    "PySide6.QtDesigner", "PySide6.QtTest", "PySide6.QtSql",
    "tkinter", "unittest", "pytest",
)


def make_icon() -> Path | None:
    """SVG'yi .ico'ya cevirir. Ayri bir donusturucu araca bagimli kalmamak icin
    Qt'nin kendi SVG oku kullaniliyor - zaten bagimliligimiz."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    if not ICON_SVG.is_file():
        print(f"uyari: {ICON_SVG} yok, simgesiz devam ediliyor")
        return None

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    renderer = QSvgRenderer(str(ICON_SVG))
    image = QImage(QSize(256, 256), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    if not image.save(str(ICON_ICO), "ICO"):
        print("uyari: .ico yazilamadi, simgesiz devam ediliyor")
        return None
    return ICON_ICO


def build() -> int:
    if shutil.which("pyinstaller") is None and not (
        Path(sys.executable).parent / "pyinstaller.exe"
    ).is_file():
        print("PyInstaller yok. Kurmak icin:")
        print(f"  {sys.executable} -m pip install pyinstaller")
        return 1

    icon = make_icon()
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        # Konsol penceresi acilmasin: bu bir GUI uygulamasi.
        "--windowed",
        "--name", "PiKontrol",
        "--paths", str(ROOT / "desktop_app" / "src"),
        "--paths", str(ROOT / "pi_protocol" / "src"),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "pyinstaller"),
        "--specpath", str(BUILD_DIR),
    ]
    if icon is not None:
        command += ["--icon", str(icon)]
    for name in HIDDEN_IMPORTS:
        command += ["--hidden-import", name]
    for name in EXCLUDES:
        command += ["--exclude-module", name]
    command.append(str(ROOT / "desktop_app" / "src" / "desktop_app" / "main.py"))

    print("calistiriliyor:", " ".join(command[:8]), "...")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = DIST_DIR / "PiKontrol.exe"
    if exe.is_file():
        print(f"\nhazir: {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
