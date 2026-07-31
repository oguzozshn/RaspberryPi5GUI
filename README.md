# Raspberry Pi 5 GUI Kontrol Paneli

Windows'tan, yerel ağdaki bir Raspberry Pi 5'i sürekli SSH açmadan yönetmek için
PySide6 tabanlı masaüstü GUI + Pi üzerinde çalışan bir arka plan agent'ı.

```
pi_protocol/   # paylaşılan WS mesaj şeması (pydantic), her iki tarafça da kullanılır
pi_agent/      # Pi'de çalışan FastAPI/uvicorn servisi
desktop_app/   # Windows'ta çalışan PySide6 istemcisi
```

Mesaj sözleşmesi ve transport kararları için bkz. `docs/PROTOCOL.md`.

## Durum: Faz 1 tamamlandı

Çalışan özellikler:

- **Dashboard** — canlı CPU kullanımı (toplam + çekirdek başına), CPU sıcaklığı,
  bellek, disk ve uptime/load average; CPU'ya göre sıralı çalışan uygulama listesi.
- **Dosyalar** — Pi'nin dosya sisteminde gezinme, Windows Explorer'dan
  sürükle-bırak ile yükleme, seçili dosyayı indirme, ilerleme çubuklu transfer kuyruğu.

Henüz **yok** (sırasıyla Faz 2-4'te gelecek): chat/pano köprüsü, servis ve
process yönetimi, güç kontrolü + GPIO, Docker + ağ bilgisi.

## Pi'ye kurulum

Bu repoyu Pi'ye kopyalayın (scp/rsync/git clone) ve **kendi kullanıcınızdan**
bir kere çalıştırın:

```bash
sudo bash pi_agent/scripts/install.sh
```

Script şunları yapar:

- Gerekli apt paketlerini kurar (`python3-venv`, `xclip`, `wl-clipboard`, ...).
- `/opt/pi-agent` altına bir venv kurup uygulamayı yükler.
- Rastgele bir pairing token üretip `/etc/pi-agent/config.toml` içine yazar (mode 600).
- systemd servisini kurar: açılışta otomatik başlar, çökerse yeniden başlar.
- Dar kapsamlı bir sudoers kuralı ekler: sadece `systemctl start/stop/restart`,
  `reboot`, `poweroff`, `journalctl` — asla `NOPASSWD:ALL` değil.

Kurulum sonunda ekrana basılan **IP ve token'ı** masaüstü uygulamasının
ilk-çalıştırma ekranına girin. Kaldırmak için `sudo bash pi_agent/scripts/uninstall.sh`.

> **Agent neden ayrı bir sistem kullanıcısı değil de sizin hesabınızla çalışıyor?**
> Yüklenen dosyaların ev dizininize sizin sahipliğinizle inmesi ve (Faz 2'de)
> pano köprüsünün sizin grafik oturumunuza erişebilmesi için. İzole bir servis
> kullanıcısı ikisini de yapamazdı.

## Masaüstü uygulamasını çalıştırma

```powershell
python -m venv .venv-desktop
.venv-desktop\Scripts\pip install -e .\pi_protocol -e ".\desktop_app[dev]"
.venv-desktop\Scripts\python -m desktop_app.main
```

İlk açılışta Pi'nin IP'si, portu ve token'ı sorulur. "Baglantiyi Test Et" ile
doğrulanır; token Windows Credential Manager'da (`keyring`) saklanır, IP ve port
`QSettings`'te tutulur.

## Geliştirme

Pi tarafı Linux'ta, masaüstü Windows'ta çalıştığı için bağımlılıkları ayrı
tutmak adına iki venv kullanılıyor.

```powershell
# pi_agent (Windows'ta yerel test icin)
python -m venv .venv-agent
.venv-agent\Scripts\pip install -e .\pi_protocol -e ".\pi_agent[dev]"
.venv-agent\Scripts\pytest pi_agent\tests -q

# desktop_app
.venv-desktop\Scripts\pytest desktop_app\tests -q
```

Agent'ı yerelde çalıştırmak için (gerçek Pi'deki `/etc/pi-agent/config.toml`
yerine `pi_agent/dev_config.toml` kullanılır):

```powershell
$env:PI_AGENT_CONFIG = "pi_agent\dev_config.toml"
.venv-agent\Scripts\python -m pi_agent.main
```

## Bilinen sınırlamalar (v1)

- **Sadece yerel ağ.** Uzaktan erişim/VPN desteği yok.
- **`ws://` (TLS yok).** Token aynı LAN'da düz metin gider — ev ağı için
  bilinçli kabul edilen bir ödünleşim. `wss://` desteği koda dokunmadan
  eklenebilecek şekilde tasarlandı (uvicorn `ssl_certfile`/`ssl_keyfile`).
- **Sürükle-bırak şu an sadece dosya kabul ediyor**, klasörler atlanıyor.
- **Transferler yeniden başlatılabilir değil**; kesilen bir aktarım baştan yapılır.
- **Windows Defender/Firewall ilk çalıştırmada uyarı verebilir** (imzasız uygulama).
- **`raspberrypi.local` Windows'ta her zaman çözümlenmeyebilir** — kurulum
  ekranına IP adresi girmek daha güvenilir; router'da DHCP rezervasyonu önerilir.
