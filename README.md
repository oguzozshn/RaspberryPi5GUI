# Raspberry Pi 5 GUI Kontrol Paneli

Windows'tan, yerel ağdaki bir Raspberry Pi 5'i sürekli SSH açmadan yönetmek için
PySide6 tabanlı masaüstü GUI + Pi üzerinde çalışan bir arka plan agent'ı.

```
pi_protocol/   # paylaşılan WS mesaj şeması (pydantic), her iki tarafça da kullanılır
pi_agent/      # Pi'de çalışan FastAPI/uvicorn servisi
desktop_app/   # Windows'ta çalışan PySide6 istemcisi
```

Mesaj sözleşmesi ve transport kararları için bkz. `docs/PROTOCOL.md`.

## Durum: Faz 4 tamamlandı (v1 kapsamı bitti)

Çalışan özellikler:

- **Dashboard** — canlı CPU kullanımı (toplam + çekirdek başına), CPU sıcaklığı,
  bellek, disk ve uptime/load average; CPU'ya göre sıralı çalışan uygulama
  listesi ve seçili process'i sonlandırma.
- **Sohbet** — yazdığınız metin Pi'nin sistem panosuna gider, Pi'de Ctrl+V ile
  herhangi bir prompt'a yapıştırırsınız (şifre göndermek için SSH oturumu açık
  tutmaya son). Pi'nin panosunu geri okuma, şifre yazarken girişi maskeleme.
- **Dosyalar** — Pi'nin dosya sisteminde gezinme, Windows Explorer'dan
  sürükle-bırak ile yükleme, seçili dosyayı indirme, ilerleme çubuklu transfer kuyruğu.
- **Servisler** — systemd birimlerini listeleme/filtreleme, başlat/durdur/yeniden
  başlat, `journalctl` log görüntüleyici.
- **Güç & GPIO** — onay isteyen yeniden başlatma/kapatma; 40-pin başlığın canlı
  görünümü (mod, seviye, satırı tutan sürücü), seçili pini HIGH/LOW sürme ve
  "Girişe al" ile geri verme.
- **Docker** — container listesi (durum/imaj/portlar), başlat/durdur/yeniden
  başlat, `docker logs` görüntüleyici, ad ve imaja göre filtreleme.
- **Ağ** — arayüzler, IP/MAC adresleri, trafik sayaçları, varsayılan ağ geçidi,
  DNS sunucuları ve Wi-Fi SSID/sinyal gücü.

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
- GPIO için `lgpio`'yu derleyip kurar. Derleme başarısız olursa kurulum devam
  eder; sadece GPIO sekmesi nedenini yazarak devre dışı kalır.

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

### Tek dosyalık exe

Python kurulu olmayan bir Windows'ta da çalışsın istiyorsanız:

```powershell
.venv-desktop\Scripts\pip install pyinstaller
.venv-desktop\Scripts\python desktop_app\scripts\build_exe.py
```

Sonuç `dist\PiKontrol.exe` (~54 MB, tek dosya). Simge `pi_agent/web/icon.svg`'den
Qt ile üretilir, ayrı bir dönüştürücü araç gerekmez. İlk açılış birkaç saniye
sürer: tek-dosya paketi kendini geçici klasöre açar.

> `keyring` arka uçları eklentiyle bulunduğu için PyInstaller'ın statik analizi
> onları göremez ve `--hidden-import` ile eklenir; eksik olsalardı uygulama
> kayıtlı token'ı okuyamaz, her açılışta kurulum ekranı gösterirdi.

Bağlantı koparsa üst çubukta **"Yeniden Baglan"** düğmesi çıkar. Deneme bilerek
otomatik değil: Pi genelde biri gidip güç düğmesine bastığı için geri gelir ve
kendi takvimiyle bağlanan bir istemci, ekranı sizin seçmediğiniz bir anda
değiştirir. Token yeniden sorulmaz (son başarılı bağlantının bilgileri kullanılır);
bağlantı kurulunca sekmeler verilerini tazeler, çünkü Pi giderken ekranda
kalanlar bayattır.

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
- **Pano köprüsü Pi'de açık bir masaüstü oturumu gerektirir.** Tamamen headless
  (SSH-only) bir Pi'de yazılacak bir pano yoktur; arayüz bunu sekmede uyarı
  olarak gösterir, sessizce başarısız olmaz.
- **Sohbet geçmişi kalıcı değil**; uygulama kapanınca silinir.
- **Process sonlandırma sudo kullanmaz** — sadece agent'ın kendi hesabına ait
  process'leri durdurabilirsiniz. Bu bilinçli: çalınan bir token ile sistem
  servislerinin öldürülmesini engeller (servisler için Servisler sekmesi var).
- **Kapatılan Pi uzaktan açılamaz.** Arayüz onay kutusunda uyarır; geri getirmek
  için fiziksel olarak gücü kesip vermek gerekir.
- **GPIO yalnızca dijital giriş/çıkış.** PWM, I2C/SPI üzerinden cihaz konuşması,
  kenar tetiklemeli olay dinleme yok.
- **Sürülen bir pin, agent dursa da sürmeye devam eder.** Kernel satırı serbest
  bırakır ama Pi 5'in pad'i yönü ve seviyeyi korur — `systemctl restart
  pi-agent` pini geri çevirmez. Arayüzdeki **"Girişe al"** düğmesi bunu yapar
  (Pi'de elle yapmak isterseniz: `pinctrl set <BCM> ip`).
- **Sahibi olmayan ama çıkışa ayarlı pinlerin seviyesi "—" gösterilir.** Onları
  okumak sürüşlerini düşüreceği için ajan bilerek dokunmuyor.
- **GPIO seviyeleri anlık okunur**, canlı akış değil — "Yenile" ile tazelenir.
- **Docker'ı kurmak size ait.** Ajan docker'ı kurmaz; kuruluysa kullanır. Kurulum
  sonrası hesabınızın `docker` grubuna eklenmesi gerekir (`install.sh` grubu
  varsa ekler) ve üyeliğin geçerli olması için `sudo systemctl restart pi-agent`.
- **Docker sekmesi `docker run`/imaj çekme/compose yapmaz** — sadece mevcut
  container'ları izleme ve başlat/durdur/yeniden başlat.
- **Container logları stdout+stderr'i birleştirir**, zaman damgasına göre
  harmanlamaz; iki akışın satırları ardışık görünür.
- **Ağ sekmesi salt okunur.** IP/Wi-Fi ayarı değiştirme yok — bu bağlantı
  üzerinden yapılacak bir hata, düzeltmek için gereken bağlantıyı keserdi.
- **Windows Defender/Firewall ilk çalıştırmada uyarı verebilir** (imzasız uygulama).
- **`raspberrypi.local` Windows'ta her zaman çözümlenmeyebilir** — kurulum
  ekranına IP adresi girmek daha güvenilir; router'da DHCP rezervasyonu önerilir.
