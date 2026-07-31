# Protokol

Bu dosya, `desktop_app` ile `pi_agent` arasındaki WebSocket kontrol kanalının
mesaj sözleşmesini belgeler. Şema kodu `pi_protocol` paketindedir
(`pi_protocol/src/pi_protocol/`); bu belge insan-okunur özet, kaynak kod
source-of-truth'tur.

## Zarf (Envelope)

Tüm mesajlar tek bir JSON zarfı içinde gönderilir (`pi_protocol.envelope.Envelope`):

```json
{
  "type": "auth.request",
  "id": "a1b2c3...",
  "ts": 1730000000.123,
  "payload": { ... }
}
```

- `type`: mesaj türü, `pi_protocol.constants.MessageType` enum değerlerinden biri.
- `id`: `uuid4().hex`. **Yanıtlar isteğin `id`'sini aynen geri döner**, böylece
  istemci hangi yanıtın hangi isteğe ait olduğunu eşleştirebilir. Sunucudan
  kendiliğinden gelen push mesajları (`stats.update`) yeni bir `id` taşır.
- `ts`: unix timestamp (float).
- `payload`: mesaj türüne özgü model.

## Bağlantı yaşam döngüsü

1. İstemci `/ws` adresine WebSocket bağlantısı açar.
2. **İlk mesaj her zaman `auth.request` olmalı** — başka bir mesajla başlanırsa sunucu bağlantıyı kapatır (kod 4401).
3. Sunucu token'ı `hmac.compare_digest` ile zamanlama-güvenli karşılaştırır:
   - Doğruysa `auth.ok` gönderir ve **`stats.update` push döngüsü hemen başlar**.
     `auth.ok` payload'ı **capabilities** taşır (bkz. aşağısı) — ayrı bir push
     mesajı olarak değil, çünkü istemci onu almadan arayüzü çizmeye başlayabilirdi.
   - Yanlışsa `auth.rejected` gönderip bağlantıyı kapatır (kod 4403).
   - Aynı kaynak IP'den 30 saniye içinde 5 başarısız denemeden sonra bağlantı hiç kabul edilmez (kod 4429).
4. Kimlik doğrulamadan sonra istekler **eşzamanlı** işlenir: her mesaj ayrı bir
   asyncio task'ına verilir. Bu önemli, çünkü `process.list` toplama işlemi
   saniyeler sürebiliyor ve sıralı işlense diğer tüm istekleri baştan bloklardı.
   Aynı sokete eşzamanlı yazımlar `wire.Connection` içindeki bir lock ile
   serileştirilir.
5. Tanınmayan bir `type` veya handler'ı olmayan bir mesaj için sunucu `error`
   zarfı döner (bağlantıyı kapatmaz).

## Mevcut mesaj türleri

| type | Yön | Payload | Açıklama |
|---|---|---|---|
| `auth.request` | istemci → sunucu | `{"token": str}` | Bağlantının ilk mesajı. |
| `auth.ok` | sunucu → istemci | `{"protocol_version": int, "capabilities": {...}}` | Kimlik doğrulama başarılı + bu Pi'nin neleri destekleyip desteklemediği. |
| `auth.rejected` | sunucu → istemci | `{"reason": str}` | Kimlik doğrulama başarısız. |
| `error` | sunucu → istemci | `{"code": str, "message": str}` | Hata; `id` varsa ilgili isteğin id'si. |
| `stats.update` | sunucu → istemci (push) | `StatsUpdatePayload` | Varsayılan 2 saniyede bir; CPU (toplam + çekirdek başına, sıcaklık, frekans), bellek, swap, diskler, uptime, load average, hostname. |
| `process.list` | istemci → sunucu | `{"limit": int, "sort_by": "cpu"\|"memory"\|"pid"\|"name"}` | Çalışan process listesi ister. |
| `process.list.result` | sunucu → istemci | `{"processes": [...], "total_count": int}` | Sıralanmış ve `limit` ile kırpılmış liste. |
| `files.list` | istemci → sunucu | `{"path": str}` | Dizin listeler; `~` genişletilir. |
| `files.list.result` | sunucu → istemci | `{"path": str, "parent": str\|null, "entries": [...]}` | Dizinler önce, sonra alfabetik. |
| `process.kill` | istemci → sunucu | `{"pid": int, "force": bool}` | `force=false` SIGTERM, `true` SIGKILL. |
| `process.kill.result` | sunucu → istemci | `{"pid": int, "ok": bool, "detail": str}` | |
| `chat.send` | istemci → sunucu | `{"text": str}` | Metni Pi'nin sistem panosuna yazar. |
| `chat.message` | sunucu → istemci | `{"text", "source": "desktop"\|"pi", "delivered_to_clipboard": bool, "detail": str}` | `chat.send`/`clipboard.pull` yanıtı. |
| `clipboard.pull` | istemci → sunucu | `{}` | Pi'nin panosunu okur. |
| `service.list` | istemci → sunucu | `{"pattern": str}` | Boş pattern = tümü. |
| `service.list.result` | sunucu → istemci | `{"services": [...]}` | Unit adına göre sıralı. |
| `service.action` | istemci → sunucu | `{"unit": str, "action": "start"\|"stop"\|"restart"}` | |
| `service.action.result` | sunucu → istemci | `{"unit", "action", "ok": bool, "detail": str}` | |
| `service.logs` | istemci → sunucu | `{"unit": str, "lines": int}` | En fazla 2000 satır. |
| `service.logs.result` | sunucu → istemci | `{"unit": str, "lines": [str]}` | |
| `power.action` | istemci → sunucu | `{"action": "reboot"\|"shutdown"}` | |
| `power.action.result` | sunucu → istemci | `{"action", "ok": bool, "detail": str}` | Başarıda soket kapanmadan yetişmeyebilir (aşağıya bkz.). |
| `gpio.list` | istemci → sunucu | `{}` | 40-pin başlığın tamamını ister. |
| `gpio.list.result` | sunucu → istemci | `{"pins": [...], "detail": str}` | Fiziksel pin numarasına göre sıralı; `detail` kullanılan gpiochip. |
| `gpio.write` | istemci → sunucu | `{"bcm": int, "value": 0\|1}` | Pini çıkışa alıp sürer. |
| `gpio.write.result` | sunucu → istemci | `{"bcm", "value", "ok": bool, "detail": str}` | |
| `docker.list` | istemci → sunucu | `{"include_stopped": bool}` | |
| `docker.list.result` | sunucu → istemci | `{"containers": [...]}` | Çalışanlar önce, sonra alfabetik. |
| `docker.action` | istemci → sunucu | `{"container": str, "action": "start"\|"stop"\|"restart"}` | |
| `docker.action.result` | sunucu → istemci | `{"container", "action", "ok": bool, "detail": str}` | |
| `docker.logs` | istemci → sunucu | `{"container": str, "lines": int}` | En fazla 2000 satır. |
| `docker.logs.result` | sunucu → istemci | `{"container": str, "lines": [str]}` | stdout + stderr birlikte. |
| `network.info` | istemci → sunucu | `{}` | |
| `network.info.result` | sunucu → istemci | `NetworkInfoResultPayload` | Arayüzler, ağ geçidi, DNS, Wi-Fi SSID/sinyal. |

`files.list` hata kodları: `not_found`, `not_a_directory`, `permission_denied`, `io_error`.
Servis hata kodları: `not_available` (systemd yok), `bad_request` (geçersiz unit adı),
`systemctl_failed`, `journalctl_failed`.
Güç/GPIO hata kodları: `not_available` (systemd ya da GPIO yok — mesaj kullanıcıya
gösterilecek nedeni taşır), `bad_request` (şemaya uymayan `action`/`value`).
Docker hata kodları: `not_available` (docker yok ya da daemon'a erişilemiyor),
`bad_request` (geçersiz container adı), `docker_failed`.

`GpioPin` alanları: `bcm`, `physical` (başlıktaki pin numarası), `mode`
(`input`/`output`), `value` (`0`/`1`, okunamadıysa `null`), `consumer` (satırı
tutan sürücü), `reserved_for` (pinin normalde bağlı olduğu arabirim, bilgi
amaçlı), `writable` (`false` ise ajan yazmayı reddeder).

## Capabilities

`auth.ok` içinde gelir; arayüz desteklenmeyen bölümleri gizlemek/uyarı göstermek
için kullanır. Her bağlantıda yeniden ölçülür, böylece Pi'ye ekran takıp yeniden
bağlanmak yeterli olur.

| Alan | Anlamı |
|---|---|
| `clipboard` | `wl-copy`/`xclip` ile Pi'nin panosuna erişilebiliyor mu. |
| `clipboard_detail` | Kullanılan araç, ya da erişilemiyorsa **nedeni** (kullanıcıya gösterilir). |
| `systemd` | `systemctl` var mı. Güç kontrolü de buna bağlı. |
| `gpio` | GPIO başlığı sürülebiliyor mu (`lgpio` + açılabilen bir gpiochip). |
| `gpio_detail` | Kullanılan yonga, ya da erişilemiyorsa **nedeni** (kullanıcıya gösterilir). |
| `docker` | Docker CLI var **ve** daemon'a erişilebiliyor mu. |
| `docker_detail` | Sunucu sürümü, ya da erişilemiyorsa **nedeni** (kullanıcıya gösterilir). |

`docker` yeteneği `docker version` çalıştırılarak ölçüldüğü için kimlik doğrulama
en fazla 5 saniye gecikebilir — ama sadece CLI kuruluyken; kurulu değilse
`shutil.which` ile anında elenir.

### Pano köprüsü nasıl çalışır

Ajan bir systemd **sistem** servisi olarak temiz bir ortamda başlar ve normalde
kullanıcının masaüstü oturumunu hiç göremez. Bu yüzden `install.sh`, unit
dosyasına `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`, `DISPLAY` ve `XAUTHORITY`
değişkenlerini yazar. Çalışma anında önce Wayland soketi (`$XDG_RUNTIME_DIR/wayland-0`)
aranır — Bookworm'da Pi 5 varsayılan olarak Wayland kullanır — bulunamazsa X11'e
düşülür. Hiçbiri yoksa `clipboard=false` döner ve arayüz nedenini gösterir.

### Unit adı doğrulaması

`service.action`/`service.logs` unit adları istemciden gelir. Komutlar shell
olmadan (`create_subprocess_exec`) çalıştırıldığı için shell enjeksiyonu söz
konusu değil; doğrulamanın amacı `--all` veya `-M host` gibi bir adın systemctl
tarafından unit yerine **seçenek** olarak okunmasını engellemek.

## Güç kontrolü

`power.action` yalnızca bir sözlük anahtarı seçer; argv istemciden gelmez:

| action | çalıştırılan komut |
|---|---|
| `reboot` | `sudo -n systemctl reboot` |
| `shutdown` | `sudo -n systemctl poweroff` |

İkisi de `install.sh`'in yazdığı sudoers kuralında birebir listelidir; `sudo -n`
kullanıldığı için kural eksikse komut parola beklemek yerine hemen hata döner.

**Yanıt garantisi tek yönlüdür.** Komut başarılıysa Pi zaten kapanmaya başlamış
olur ve `power.action.result` sokete yetişmeyebilir — istemci bunu beklenen
davranış olarak gösterir. Başarısızlık (ör. sudoers kuralı yok) ise güvenilir
şekilde geri döner; kullanıcının görmesi gereken durum da budur.

## GPIO

Erişim `lgpio` üzerindendir: Pi 5'te RP1'i kernel'in gpiochip karakter aygıtı
üzerinden sürer. Eski `RPi.GPIO`/sysfs yolu Pi 5'te çalışmaz.

- **Yonga etikete göre bulunur**, numaraya göre değil: başlık bankası Bookworm
  kernel'leri arasında `gpiochip4` → `gpiochip0` diye yer değiştirdi, etiket
  (`pinctrl-rp1`) ise sabit kaldı.
- **`gpio.list` tahribatsızdır.** Sadece örneklenen pinler girişe alınıp okunur
  ve *hemen* serbest bırakılır; aksi hâlde ajan Pi'deki diğer programlara
  başlığın tamamını tutuyormuş gibi görünürdü. Başka bir sürücünün (SPI, I2C,
  PWM...) tuttuğu satır talep edilmez, `value: null` döner.
- **`gpio.write` pini çıkış olarak ayırır ve ayırmayı bırakmaz** — sürülen bir
  pin sonraki listelemede seviyesini korumalı. Ajan süreci bittiğinde kernel
  satırları otomatik serbest bırakır.
- **BCM 0 ve 1'e yazma engellidir** (HAT ID EEPROM). Bu satırları sürmek açılışta
  HAT algılamayı bozabilir ve normal bir kabloya gerek duymaz; `writable: false`
  ile bildirilir, arayüz de düğmeleri kapatır.
- Diğer özel işlevli pinler (I2C/SPI/UART/PWM) `reserved_for` ile işaretlenir
  ama yazılabilir kalır; arayüz onaylatmadan önce uyarır.
- `lgpio` derlenmiş ve Linux'a özgü olduğu için ajanın **zorunlu** bağımlılığı
  değildir. Yoksa `gpio=false` döner, `gpio_detail` nedenini taşır ve ajan geri
  kalan her şeyi yapmaya devam eder.

## Docker

Ajan docker CLI'ını `create_subprocess_exec` ile çağırır; docker SDK'sı ek bir
bağımlılık olurdu ve socket izinleri açısından hiçbir şey kazandırmazdı.

- **`sudo` kullanılmaz.** Ajanın hesabı `docker` grubundaysa daemon'a doğrudan
  erişir; değilse `not_available` döner. Not: `docker` grubu üyeliği zaten root
  ile eşdeğerdir, bu yüzden ayrıca sudoers kuralı eklemenin bir anlamı yok.
- **Container adları doğrulanır** (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`) — unit
  adlarındaki gerekçenin aynısı: `--all` gibi bir adın CLI tarafından container
  yerine **seçenek** olarak okunmasını engellemek.
- **`docker ps --format {{json .}}`** satır başına bir JSON nesnesi verir (dizi
  değil). `State` alanı 20.10 öncesi CLI'larda yok; o durumda `Status`'un ilk
  kelimesinden türetilir.
- **Loglarda stdout ve stderr birleştirilir.** Çoğu imaj stderr'e yazar; onu
  atmak, insanların log görüntüleyiciyi açma sebebini atmak olurdu. İki akış
  zaman damgasına göre değil, ardışık olarak eklenir.
- Sadece izleme ve start/stop/restart var: `docker run`, imaj çekme ve compose
  yok — bunlar bu arayüzün LAN token'ıyla güvenle toplayamayacağı argümanlar
  ister.

## Ağ bilgisi

`network.info` tamamen okuma amaçlıdır; ağ yapılandırmasını değiştiren hiçbir
mesaj yok — bu bağlantı üzerinden yapılacak bir hata, onu düzeltmek için gereken
bağlantıyı keserdi.

- Arayüzler, MAC/adresler ve sayaçlar `psutil`'den gelir (Windows'ta da çalışır).
- Varsayılan ağ geçidi `/proc/net/route`'tan okunur: adresler little-endian hex
  (`0102A8C0` = 192.168.2.1) ve birden fazla varsayılan rota varsa **en düşük
  metrik** kazanır — kernel'in seçtiği rota da odur.
- DNS `/etc/resolv.conf`, kablosuz arayüz listesi `/proc/net/wireless`, SSID ve
  sinyal `iw dev <arayuz> link` çıktısından ayrıştırılır. Dosyaların/aracın
  bulunmaması hata değildir; alanlar boş döner.

## Dosya transferi (HTTP, WS değil)

Dosya baytları WS kontrol kanalından **değil**, aynı FastAPI sürecindeki ayrı
HTTP route'larından akar — büyük bir transfer, gecikmeye duyarlı stats/chat
çerçevelerini head-of-line bloklamasın diye.

| Route | Açıklama |
|---|---|
| `PUT /files/upload?path=<hedef>` | İstek gövdesi chunked stream olarak yazılır. Önce `<hedef>.part` dosyasına yazılıp başarıda rename edilir, böylece yarıda kesilen transfer hedefte bozuk dosya bırakmaz. Yanıt: `{"path", "size_bytes"}`. |
| `GET /files/download?path=<kaynak>` | `FileResponse` ile streaming. |

İkisi de `Authorization: Bearer <token>` header'ı ister (WS ile aynı token).
Hata kodları: 401 (token yok), 403 (token yanlış / izin yok), 404 (yol yok),
400 (hedef dizin / kaynak dizin).

İstemci tarafı 1 MB'lık parçalar hâlinde okur/yazar (`file_client.CHUNK_SIZE`),
böylece bellek kullanımı dosya boyutundan bağımsız sabit kalır.

## Sürüm geçmişi

| `PROTOCOL_VERSION` | Eklenenler |
|---|---|
| 1 | auth, stats, process, files |
| 2 | chat/clipboard köprüsü, systemd servisleri, capabilities |
| 3 | `power.action`, `gpio.list`/`gpio.write` |
| 4 | `docker.*`, `network.info` |
