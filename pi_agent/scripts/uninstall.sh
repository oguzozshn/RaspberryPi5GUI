#!/usr/bin/env bash
# Removes pi-agent: service, sudoers rule, config, installed files.
# Usage: sudo bash pi_agent/scripts/uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Bu script root olarak calistirilmali: sudo bash uninstall.sh" >&2
  exit 1
fi

systemctl disable --now pi-agent 2>/dev/null || true
rm -f /etc/systemd/system/pi-agent.service
systemctl daemon-reload

rm -f /etc/sudoers.d/pi-agent
rm -rf /opt/pi-agent
rm -rf /etc/pi-agent

echo "pi-agent kaldirildi."
echo "Not: apt ile kurulan paketler (xclip, wl-clipboard, qrencode, rsync) ve"
echo "     kullaniciya eklenen grup uyelikleri kaldirilmadi, gerekiyorsa elle temizleyin."
