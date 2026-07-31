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
| `auth.ok` | sunucu → istemci | `{"protocol_version": int}` | Kimlik doğrulama başarılı. |
| `auth.rejected` | sunucu → istemci | `{"reason": str}` | Kimlik doğrulama başarısız. |
| `error` | sunucu → istemci | `{"code": str, "message": str}` | Hata; `id` varsa ilgili isteğin id'si. |
| `stats.update` | sunucu → istemci (push) | `StatsUpdatePayload` | Varsayılan 2 saniyede bir; CPU (toplam + çekirdek başına, sıcaklık, frekans), bellek, swap, diskler, uptime, load average, hostname. |
| `process.list` | istemci → sunucu | `{"limit": int, "sort_by": "cpu"\|"memory"\|"pid"\|"name"}` | Çalışan process listesi ister. |
| `process.list.result` | sunucu → istemci | `{"processes": [...], "total_count": int}` | Sıralanmış ve `limit` ile kırpılmış liste. |
| `files.list` | istemci → sunucu | `{"path": str}` | Dizin listeler; `~` genişletilir. |
| `files.list.result` | sunucu → istemci | `{"path": str, "parent": str\|null, "entries": [...]}` | Dizinler önce, sonra alfabetik. |

`files.list` hata kodları: `not_found`, `not_a_directory`, `permission_denied`, `io_error`.

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

## Sonraki fazlarda eklenecek türler (henüz implemente edilmedi)

- **Faz 2**: `chat.send` (Pi panosuna yazma), `service.list`/`service.action`, `process.kill`, `logs.tail`.
- **Faz 3**: `power.reboot`, `power.shutdown`, `gpio.read`, `gpio.write`.
- **Faz 4**: `docker.list`/`docker.action`/`docker.logs`, `network.info`.
