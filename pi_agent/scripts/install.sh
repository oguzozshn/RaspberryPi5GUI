#!/usr/bin/env bash
# One-time bootstrap for pi_agent on a Raspberry Pi 5. Idempotent: safe to re-run
# (re-running preserves the existing pairing token instead of rotating it).
#
# Usage: from a checked-out copy of this repo, ON the Pi:
#   sudo bash pi_agent/scripts/install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_DIR=/opt/pi-agent
CONFIG_DIR=/etc/pi-agent
CONFIG_FILE="$CONFIG_DIR/config.toml"
DEFAULT_PORT=8765

if [[ $EUID -ne 0 ]]; then
  echo "Bu script root olarak calistirilmali: sudo bash install.sh" >&2
  exit 1
fi

# The agent runs as the account that invoked sudo, NOT an isolated system user:
# uploaded files must land in your home directory owned by you, and the Phase 2
# clipboard bridge has to reach your graphical session.
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "HATA: Bu scripti normal kullanicinizdan 'sudo bash install.sh' ile calistirin." >&2
  echo "      (dogrudan root shell'den degil - agent sizin kullanicinizla calismali)" >&2
  exit 1
fi
echo "==> Agent su kullanici ile calisacak: $TARGET_USER"

echo "==> Pi 5 tespiti"
if [[ -f /proc/device-tree/model ]] && grep -qi "Raspberry Pi 5" /proc/device-tree/model; then
  echo "Raspberry Pi 5 tespit edildi."
else
  echo "Uyari: Raspberry Pi 5 tespit edilemedi, kuruluma yine de devam ediliyor." >&2
fi

echo "==> Sistem paketleri kuruluyor"
apt-get update -qq
apt-get install -y python3-venv python3-pip xclip wl-clipboard qrencode rsync >/dev/null

echo "==> Grup uyelikleri"
for grp in gpio dialout video docker; do
  if getent group "$grp" >/dev/null 2>&1; then
    usermod -aG "$grp" "$TARGET_USER"
  fi
done

echo "==> Uygulama dosyalari kopyalaniyor: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '*.egg-info' \
  "$REPO_ROOT/pi_protocol" "$REPO_ROOT/pi_agent" "$INSTALL_DIR/"

echo "==> Python sanal ortami kuruluyor"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR/pi_protocol" -e "$INSTALL_DIR/pi_agent" -q

echo "==> Yapilandirma hazirlaniyor: $CONFIG_FILE"
mkdir -p "$CONFIG_DIR"
TOKEN=""
if [[ -f "$CONFIG_FILE" ]]; then
  TOKEN="$(grep -oP '(?<=token = ")[^"]+' "$CONFIG_FILE" || true)"
  [[ -n "$TOKEN" ]] && echo "Mevcut pairing token korunuyor."
fi
if [[ -z "$TOKEN" ]]; then
  TOKEN="$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
cat > "$CONFIG_FILE" <<EOF
[auth]
token = "$TOKEN"

[server]
host = "0.0.0.0"
port = $DEFAULT_PORT

[stats]
interval_seconds = 2.0
EOF
chown -R "$TARGET_USER":"$TARGET_USER" "$INSTALL_DIR" "$CONFIG_DIR"
chmod 600 "$CONFIG_FILE"

echo "==> Sudoers kurali kuruluyor"
SUDOERS_TMP="$(mktemp)"
sed "s/__USER__/$TARGET_USER/g" "$REPO_ROOT/pi_agent/scripts/sudoers.d_pi-agent" > "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP"
install -m 440 "$SUDOERS_TMP" /etc/sudoers.d/pi-agent
rm -f "$SUDOERS_TMP"

echo "==> systemd servisi kuruluyor"
sed "s/__USER__/$TARGET_USER/g" "$REPO_ROOT/pi_agent/scripts/pi-agent.service" \
  > /etc/systemd/system/pi-agent.service
systemctl daemon-reload
systemctl enable pi-agent
systemctl restart pi-agent

echo "==> Guvenlik duvari (varsa)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "$DEFAULT_PORT"/tcp comment 'pi-agent' || true
fi

echo "==> Dogrulama"
sleep 2
if curl -sf "http://localhost:$DEFAULT_PORT/healthz" >/dev/null; then
  IP_ADDR="$(hostname -I | awk '{print $1}')"
  echo ""
  echo "================================================================"
  echo " pi-agent calisiyor (systemctl status pi-agent)."
  echo " Kullanici: $TARGET_USER"
  echo " IP:        $IP_ADDR"
  echo " Port:      $DEFAULT_PORT"
  echo " Token:     $TOKEN"
  echo ""
  echo " Bu IP ve token'i masaustu uygulamasinin kurulum ekranina girin."
  echo "================================================================"
else
  echo "HATA: /healthz yanit vermedi. Detay icin: journalctl -u pi-agent -n 50" >&2
  exit 1
fi
