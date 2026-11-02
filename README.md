# FMB125 → VPS → MQTT (GPS + TPMS)

Server Python menerima data **GPS** (Codec 8 Extended) dan **TPMS via RS232** (Codec 12) dari Teltonika FMB125, lalu meneruskannya ke broker **MQTT Mosquitto**.

| | |
|---|---|
| **Status** | ✅ Pipeline GPS + TPMS berhasil |
| **Terakhir dites** | 8 Oktober 2026 |
| **Kode aktif (v1)** | [`server/gps_server.py`](server/gps_server.py) (di VPS: `/root/gps_server.py`) ✅ sudah jalan |
| **Kode NEXT (v2)** | [`server/gps_server_v2.py`](server/gps_server_v2.py) 🟡 *(belum di-test di VPS/FMB125, perlu deploy di VPS)*, lihat [bagian 10](#10-next-gps_server_v2py) |
| **Aplikasi Android** | [`MyApplication/`](MyApplication/) (GPS Monitor), lihat [bagian 6.5](#65-aplikasi-android-gps-monitor) |

---

## Struktur Repository

```text
.
├── README.md                 ← dokumentasi ini
├── server/                   ← kode Python untuk VPS
│   ├── gps_server.py         ← v1 (sedang jalan di VPS)
│   ├── gps_server_v2.py      ← v2 NEXT (belum di-test di VPS)
│   └── requirements.txt      ← dependensi Python (paho-mqtt)
├── MyApplication/            ← aplikasi Android (buka folder ini di Android Studio)
│   └── app/src/main/java/com/gpsaxius/monitor/MainActivity.kt
└── docs/
    └── app-icon-source.jpeg  ← gambar sumber ikon aplikasi
```

> Untuk mengunduh semua file sekaligus: tombol **Code → Download ZIP** di GitHub.

---

## Daftar Isi

1. [Ringkasan Cepat](#1-ringkasan-cepat)
2. [Arsitektur](#2-arsitektur)
3. [VPS](#3-vps)
4. [FMB125](#4-fmb125)
5. [Protokol & Format Data](#5-protokol--format-data)
6. [MQTT](#6-mqtt)
7. [Menjalankan Project](#7-menjalankan-project)
8. [Troubleshooting](#8-troubleshooting)
9. [Struktur Kode `gps_server.py`](#9-struktur-kode-gps_serverpy)
10. [NEXT: `gps_server_v2.py`](#10-next-gps_server_v2py) *(belum di-test, perlu deploy di VPS)*
11. [Known Issues & Saran Perbaikan](#11-known-issues--saran-perbaikan)
12. [Keamanan](#12-keamanan)
13. [Status & Roadmap](#13-status--roadmap)
14. [Kalimat Kunci untuk Melanjutkan](#14-kalimat-kunci-untuk-melanjutkan)

---

## 1. Ringkasan Cepat

| Item | Nilai |
|---|---|
| VPS IP publik | `202.10.47.206` |
| Hostname | `vps.gpsaxius.id` |
| SSH | `ssh root@202.10.47.206` |
| Kode server | `/root/gps_server.py` |
| Virtualenv | `/root/gps-env` |
| Port GPS (TCP) | `4356` |
| Port MQTT | `1883` (tanpa auth, tanpa TLS) |
| IMEI FMB125 aktif | `352016700616766` |
| Topic GPS | `vehicle/352016700616766/gps` |
| Topic TPMS | `vehicle/352016700616766/tpms` |

> ⚠️ IMEI lama `350544509271766` **tidak dipakai lagi**.

---

## 2. Arsitektur

```text
 TPMS Sensor
     │ RS232
     ▼
┌─────────────────┐
│     FMB125      │  GPS + RS232
└────────┬────────┘
         │ TCP :4356 (internet / GSM)
         ▼
┌─────────────────────────────┐
│  VPS 202.10.47.206          │
│  ├─ gps_server.py (Python)  │
│  └─ Mosquitto MQTT :1883    │
└────────┬────────────────────┘
         │ MQTT
   ┌─────┴──────┐
   ▼            ▼
 Android      SCADA
```

---

## 3. VPS

| Item | Nilai |
|---|---|
| Provider | Rumahweb VPS |
| Hostname | `vps.gpsaxius.id` |
| IP publik | `202.10.47.206` |
| IP privat | `10.0.169.129` |
| OS | Ubuntu 24.04 |
| User | `root` |
| Password | 🔒 **Simpan di password manager, jangan tulis di file ini** |

### Firewall (UFW)

| Port | Fungsi |
|---|---|
| `22/tcp` | SSH |
| `4356/tcp` | FMB125 GPS |
| `1883/tcp` | MQTT |

```bash
ufw status
```

### File penting

| Path | Keterangan |
|---|---|
| `/root/gps_server.py` | Server Python |
| `/root/gps-env/` | Python virtual environment (berisi `paho-mqtt`) |
| `/etc/mosquitto/conf.d/gps.conf` | Konfigurasi Mosquitto |

Isi `gps.conf` saat ini:

```text
listener 1883 0.0.0.0
allow_anonymous true
```

---

## 4. FMB125

### Konfigurasi server di device

| Item | Nilai |
|---|---|
| Device | Teltonika FMB125 |
| IMEI | `352016700616766` |
| Server | `202.10.47.206` |
| Port | `4356` |
| Protocol | TCP |

### Wiring RS232

| Pin FMB125 | Fungsi |
|---|---|
| Pin 3 | RS232 RX |
| Pin 4 | RS232 TX |
| Pin 7 | GND |

```text
Device TX  → FMB125 RX (Pin 3)
Device GND → FMB125 GND (Pin 7)
Device RX  ← FMB125 TX (Pin 4)   # hanya jika komunikasi dua arah
```

> ⚠️ Gunakan level tegangan **RS232**, bukan USB-TTL langsung.

---

## 5. Protokol & Format Data

### 5.1 Alur koneksi TCP

```text
1. FMB125 → [2 byte panjang IMEI][IMEI ASCII]
2. Server → 0x01                         (IMEI diterima)
3. FMB125 → [Preamble 4B][Data Size 4B][Data][CRC 4B]   (berulang)
4. Server → ACK 4 byte (jumlah record / quantity)
```

Byte pertama `Data` = **Codec ID**:

| Codec ID | Codec | Isi | Dikirim ke |
|---|---|---|---|
| `0x8E` | Codec 8 Extended | GPS + IO | `vehicle/{IMEI}/gps` |
| `0x0C` | Codec 12 | Data RS232 (ASCII) | `vehicle/{IMEI}/tpms` (jika diawali `TPMS;`) |

### 5.2 Codec 12 (RS232)

Contoh tes sederhana: device mengirim `HELLO\r\n`, server menampilkan:

```text
[RS232] CODEC 12 TERDETEKSI
[RS232] ASCII : 'HELLO\r\n'
```

ACK Codec 12 = 4 byte quantity.

### 5.3 Format TPMS

```text
TPMS;<ban>;<pressure>;<temperature>;<ban>;<pressure>;<temperature>;...
```

Contoh 8 ban:

```text
TPMS;1;32.50;28.40;2;34.20;29.10;3;31.80;27.60;4;35.10;30.20;5;33.70;28.90;6;32.90;29.50;7;34.80;30.80;8;31.60;27.90
```

| Field | Satuan |
|---|---|
| Pressure | PSI |
| Temperature | °C |

> Parser saat ini **wajib tepat 8 ban** (25 field setelah di-split `;`).

### 5.4 Hasil tes TPMS (8 Okt 2026)

| Ban | Pressure | Temperature |
|---|---:|---:|
| 1 | 32.5 PSI | 28.4 °C |
| 2 | 34.2 PSI | 29.1 °C |
| 3 | 31.8 PSI | 27.6 °C |
| 4 | 35.1 PSI | 30.2 °C |
| 5 | 33.7 PSI | 28.9 °C |
| 6 | 32.9 PSI | 29.5 °C |
| 7 | 34.8 PSI | 30.8 °C |
| 8 | 31.6 PSI | 27.9 °C |

---

## 6. MQTT

### 6.1 Broker

| Item | Nilai |
|---|---|
| Software | Mosquitto |
| Host | `202.10.47.206` (dari luar) / `localhost` (dari VPS) |
| Port | `1883` |
| Username / Password | kosong |
| TLS | OFF |

```bash
systemctl status mosquitto
```

```bash
systemctl restart mosquitto
```

### 6.2 Topic & payload

**GPS** → `vehicle/352016700616766/gps`

```json
{
  "timestamp": "2026-10-08 08:58:42 UTC",
  "latitude": -6.9161633,
  "longitude": 107.5091116,
  "altitude": 699,
  "angle": 266,
  "satellites": 14,
  "speed": 0
}
```

**TPMS** → `vehicle/352016700616766/tpms`

```json
{
  "tire1": { "pressure_psi": 32.5, "temperature_c": 28.4 },
  "tire2": { "pressure_psi": 34.2, "temperature_c": 29.1 },
  "...":   "...",
  "tire8": { "pressure_psi": 31.6, "temperature_c": 27.9 }
}
```

### 6.3 Subscribe (di VPS)

Semua data device:

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/#' -v
```

Hanya GPS:

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/gps' -v
```

Hanya TPMS:

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/tpms' -v
```

### 6.4 Tes MQTT lokal

Terminal 1:

```bash
mosquitto_sub -h localhost -t "test"
```

Terminal 2:

```bash
mosquitto_pub -h localhost -t "test" -m "HELLO MQTT"
```

### 6.5 Aplikasi Android (GPS Monitor)

Kode ada di folder [`MyApplication/`](MyApplication/). Buka folder ini di Android Studio, **bukan** root repo.

| Item | Nilai |
|---|---|
| Nama aplikasi | GPS Monitor |
| Package | `com.gpsaxius.monitor` |
| Kode utama | `MyApplication/app/src/main/java/com/gpsaxius/monitor/MainActivity.kt` |
| Library MQTT | Eclipse Paho `mqttv3` 1.2.5 |
| Min / target SDK | 26 (Android 8.0) / 37 |
| Broker | `tcp://202.10.47.206:1883` (hardcode di `MainActivity.kt`) |
| Topic | `vehicle/352016700616766/gps` dan `vehicle/352016700616766/tpms` (hardcode) |

**Fitur:**

- Status koneksi MQTT dengan auto-reconnect
- GPS: kecepatan, satelit, lat/lon, ketinggian, arah, waktu GPS, dan tombol **buka di Google Maps**
- TPMS 8 ban: tekanan (PSI) dan temperatur (°C), dengan warna status NORMAL / PERINGATAN / BAHAYA
- Alarm: notifikasi per ban saat kritis dan suara TTS bahasa Indonesia
- Pengaturan batas alarm (tekanan min/maks, temperatur maks), tersimpan di HP

**Batas alarm default:**

| Parameter | Default |
|---|---|
| Tekanan minimum | 90 PSI |
| Tekanan maksimum | 120 PSI |
| Temperatur maksimum | 80 °C |

> ⚠️ Peringatan dan bahaya: PERINGATAN muncul 5 PSI sebelum batas tekanan atau 10 °C sebelum batas temperatur. Dengan data tes (32–35 PSI), semua ban akan tampil **BAHAYA**. Sesuaikan lewat tombol pengaturan alarm di aplikasi.

**Catatan aplikasi (belum diperbaiki):**

- Alarm hanya jalan saat aplikasi terbuka di layar (belum ada Foreground Service)
- Di Android 15+, tampilan bisa tertutup status bar atau tombol navigasi (belum ada penanganan edge-to-edge insets)
- Saat layar diputar, data di layar kosong sampai pesan MQTT berikutnya masuk

**Tes manual dengan aplikasi MQTT lain:** isi broker `202.10.47.206`, port `1883`, username dan password kosong, TLS OFF, lalu subscribe `vehicle/352016700616766/#`.

✅ GPS dan TPMS sudah berhasil diterima di HP.

---

## 7. Menjalankan Project

**1. Login ke VPS**

```bash
ssh root@202.10.47.206
```

**2. Aktifkan environment**

```bash
source /root/gps-env/bin/activate
```

**3. Cek syntax** (tidak ada output = OK)

```bash
python3 -m py_compile /root/gps_server.py
```

**4. Jalankan server**

```bash
/root/gps-env/bin/python /root/gps_server.py
```

Output yang diharapkan: `[SERVER] Listening on 0.0.0.0:4356`

**5. Buka terminal SSH kedua, subscribe MQTT**

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/#' -v
```

**6. Nyalakan FMB125**, pastikan device mengarah ke `202.10.47.206:4356`.

> Server masih dijalankan manual. Kalau terminal SSH ditutup, server ikut berhenti (belum ada `systemd`).

---

## 8. Troubleshooting

### Port 4356 sudah dipakai

```bash
ss -ltnp | grep :4356
```

Cari PID-nya, contoh `users:(("python3",pid=27647,fd=3))`, lalu matikan:

```bash
kill 27647
```

Kalau tidak berhenti:

```bash
kill -9 27647
```

Setelah itu jalankan server lagi (langkah 4 di bagian 7).

### Data MQTT tidak muncul

Cek berurutan:

```bash
systemctl status mosquitto
```

```bash
ss -ltnp | grep :1883
```

```bash
ufw status
```

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/#' -v
```

Cek juga:

- Apakah log server menampilkan `[IMEI] 352016700616766`? Kalau tidak, FMB125 belum terkoneksi (cek APN/GPRS dan setting server di device).
- Apakah muncul `[MQTT] ... published → ...`? Kalau tidak, paket belum ter-parse.
- TPMS tidak muncul padahal `[RS232] ASCII` terlihat? Cek format, harus tepat 25 field (lihat log `[TPMS] Format tidak sesuai`).

---

## 9. Struktur Kode `gps_server.py`

| Fungsi | Tugas |
|---|---|
| `main()` | Listen di `0.0.0.0:4356`, membuat 1 thread per koneksi |
| `client_worker()` | Membungkus `handle_client` dengan try/except, lalu menutup socket |
| `handle_client()` | Membaca IMEI, kirim `0x01`, loop baca frame (preamble, size, data, CRC) |
| `process_packet()` | Routing berdasarkan Codec ID (`0x8E` / `0x0C`) |
| `parse_codec_8_extended()` | Parse GPS dan IO, publish GPS, kirim ACK |
| `parse_codec_12()` | Parse RS232, parse TPMS, publish TPMS, kirim ACK |
| `read_exact()` | Membaca tepat N byte dari socket |

### Konfigurasi di dalam kode

| Variabel | Default | Fungsi |
|---|---|---|
| `HOST`, `PORT` | `0.0.0.0`, `4356` | Alamat listen TCP |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` | Broker MQTT |
| `SHOW_RAW_HEX` | `False` | `True` = tampilkan hex mentah setiap paket |
| `DISPLAY_IO_IDS` | `[]` | IO ID yang ditampilkan di log, misalnya `[239, 240, 21]` |

IO ID yang pernah terlihat dari FMB125: `239, 240, 21, 200, 69, 181, 182, 66, 67, 68, 201, 241, 16`.

Dependensi: `paho-mqtt` (terpasang di `/root/gps-env`, daftar ada di [`server/requirements.txt`](server/requirements.txt)). Untuk install di VPS baru:

```bash
/root/gps-env/bin/pip install -r requirements.txt
```

---

## 10. NEXT: `gps_server_v2.py`

> 🟡 **Status: (belum di-test di VPS / FMB125 asli, perlu deploy di VPS)**
>
> Sudah lolos tes simulator di luar VPS (lihat 10.3). File v1 `gps_server.py` **tidak diubah** dan tetap bisa dipakai sebagai cadangan.

### 10.1 Apa yang berubah

| # | Perubahan | Mengatasi Known Issue |
|---|---|---|
| 1 | IMEI disimpan per koneksi (class `Session`), bukan variabel global | #1 |
| 2 | Validasi preamble `00 00 00 00` dan CRC-16/IBM. Paket rusak dibalas ACK `0` supaya device mengirim ulang | #2 |
| 3 | Socket timeout `SOCKET_TIMEOUT = 600` detik | #3 |
| 4 | Buffer RS232 per koneksi: data dikumpulkan sampai ada newline | #4 |
| 5 | TPMS jumlah ban dinamis (jumlah field kelipatan 3) | #5 |
| 6 | Payload GPS ditambah `"valid": true/false` (berdasarkan `satellites > 0`) | #6 |
| 7 | Variabel loop dirapikan, parser memakai class `Reader` dengan cek panjang | #7 |
| 8 | Error parsing tidak memutus koneksi. Paket tetap di-ACK agar device tidak mengirim ulang terus | — |
| 9 | MQTT `connect_async` dan auto-reconnect, kompatibel paho-mqtt 1.x dan 2.x | — |
| 10 | Log memakai waktu dan IMEI: `2026-11-02 03:22:44 [352016700616766] [GPS] ...` | — |
| 11 | GPS di-publish **setelah** record selesai di-parse lengkap | — |

**Yang tidak berubah:** port `4356`, setting FMB125, topic MQTT, format payload TPMS. Aplikasi di HP tidak perlu diubah.

### 10.2 Konfigurasi baru di `gps_server_v2.py`

| Variabel | Default | Keterangan |
|---|---|---|
| `SOCKET_TIMEOUT` | `600` | Detik tanpa data sebelum koneksi ditutup. Harus **lebih besar** dari interval kirim FMB125 saat diam/parkir |
| `CHECK_CRC` | `True` | `False` = matikan cek CRC (hanya untuk debug) |
| `RS232_REQUIRE_NEWLINE` | `True` | `True` = tunggu `\n` sebelum proses. `False` = langsung proses setiap paket (perilaku v1) |
| `MAX_PACKET_SIZE` | `65536` | Batas ukuran 1 paket |

> ⚠️ **Penting soal `RS232_REQUIRE_NEWLINE`:** perangkat TPMS harus mengirim `\r\n` di akhir setiap baris. Cek log v1: kalau `[RS232] HEX` berakhiran `0d 0a`, berarti aman. Kalau tidak, set `RS232_REQUIRE_NEWLINE = False`. Tanda masalahnya, log v2 terus menampilkan `Menunggu sisa data (belum ada newline)` dan TPMS tidak pernah publish.

### 10.3 Hasil tes simulator (2 Nov 2026, bukan di VPS)

Dites dengan Mosquitto asli dan simulator FMB125 (paket Codec 8E dan Codec 12 dengan CRC):

| Tes | Hasil |
|---|---|
| CRC-16 cocok dengan contoh dokumentasi Teltonika (`C7CF`) | ✅ |
| 2 device bersamaan, data masuk ke topic IMEI masing-masing | ✅ |
| GPS: lat/lon benar, `valid: true` | ✅ |
| TPMS 8 ban dalam 1 paket | ✅ |
| TPMS terpotong di 2 paket, digabung lalu publish 1× | ✅ |
| TPMS 6 ban (device lain, buffer terpisah) | ✅ |
| TPMS format salah tidak di-publish | ✅ |
| CRC salah dibalas ACK 0, tidak di-publish | ✅ |
| GPS `satellites = 0` menghasilkan `valid: false` | ✅ |
| Paket terpotong tetap di-ACK dan koneksi tetap hidup | ✅ |
| Koneksi diam ditutup setelah timeout | ✅ |

**Belum dites:** FMB125 asli, sinyal GSM nyata, TPMS asli, versi paho-mqtt di VPS.

### 10.4 Cara deploy ke VPS *(belum dilakukan)*

**1. Upload file** (dari komputer Windows, di dalam folder `server/` repo ini)

```bash
scp gps_server_v2.py root@202.10.47.206:/root/
```

**2. Login dan cek syntax**

```bash
ssh root@202.10.47.206
```

```bash
/root/gps-env/bin/python -m py_compile /root/gps_server_v2.py
```

**3. Hentikan v1** (tekan `Ctrl+C` di terminal v1, atau cari PID-nya)

```bash
ss -ltnp | grep :4356
```

```bash
kill <PID>
```

**4. Jalankan v2**

```bash
/root/gps-env/bin/python /root/gps_server_v2.py
```

Output yang diharapkan: `[SERVER] v2 listening on 0.0.0.0:4356`

**5. Terminal kedua, pantau MQTT**

```bash
mosquitto_sub -h localhost -t 'vehicle/352016700616766/#' -v
```

### 10.5 Checklist tes di VPS

- [ ] Server v2 jalan tanpa error
- [ ] Log menampilkan `[IMEI] 352016700616766 accepted`
- [ ] Tidak ada `[CRC] TIDAK COCOK` pada paket normal
- [ ] GPS muncul di MQTT dan ada field `"valid"`
- [ ] TPMS 8 ban muncul di MQTT
- [ ] HP Android tetap menerima GPS dan TPMS
- [ ] FMB125 reconnect normal setelah koneksi putus atau timeout
- [ ] Biarkan jalan ≥1 jam, tidak ada error berulang

Kalau semua ✅, ubah status di README ini menjadi "sudah dites" dan jadikan v2 versi utama (lanjut Tahap B: `systemd`).

### 10.6 Rollback (kembali ke v1)

Hentikan v2 (`Ctrl+C`), lalu jalankan:

```bash
/root/gps-env/bin/python /root/gps_server.py
```

---

## 11. Known Issues & Saran Perbaikan

Hasil review kode **v1** (`gps_server.py`). Sistem saat ini **berjalan untuk 1 device**, tapi poin di bawah perlu dibereskan sebelum production atau multi-vehicle.

> Poin #1–#7 sudah diperbaiki di **v2** *(belum di-test, perlu deploy di VPS)*. Poin #8 menunggu Tahap B.

| # | Prioritas | Masalah | Dampak | Saran |
|---|---|---|---|---|
| 1 | 🔴 Tinggi | `CURRENT_IMEI` adalah variabel **global** yang dipakai bersama oleh semua thread | Dengan ≥2 device, data device A bisa ter-publish ke topic IMEI device B | Simpan IMEI per koneksi lalu oper sebagai parameter ke `process_packet` dan parser |
| 2 | 🟠 Sedang | CRC dan preamble tidak divalidasi | Paket rusak tetap diproses dan di-ACK | Validasi CRC-16/IBM dan pastikan preamble = `00 00 00 00` |
| 3 | 🟠 Sedang | Socket tanpa timeout | Koneksi GSM yang putus diam-diam membuat thread menggantung selamanya | `conn.settimeout(300)` atau aktifkan TCP keepalive |
| 4 | 🟠 Sedang | Data RS232 tidak di-buffer | Baris TPMS yang terpecah ke 2 paket Codec 12 gagal di-parse | Buffer per koneksi, proses data setelah ketemu `\r\n` |
| 5 | 🟡 Rendah | Parser TPMS wajib tepat 8 ban (`len(parts) == 25`) | Kendaraan dengan jumlah ban lain ditolak | Cek `(len(parts) - 1) % 3 == 0` agar jumlah ban dinamis |
| 6 | 🟡 Rendah | GPS tetap di-publish saat `satellites == 0` | Koordinat 0 atau posisi lama terkirim seolah valid | Tambahkan field `"valid": satellites > 0` |
| 7 | 🟡 Rendah | Variabel loop `i` dipakai ganda (loop TPMS di dalam loop Codec 12) | Belum menimbulkan bug, tapi membingungkan | Ganti nama variabel loop TPMS, misalnya `t` |
| 8 | 🟡 Rendah | Server dijalankan manual | Mati saat SSH ditutup atau VPS reboot | Buat service `systemd` |

---

## 12. Keamanan

⚠️ Konfigurasi saat ini **hanya untuk testing**:

- MQTT `1883` terbuka ke internet dengan `allow_anonymous true`. Siapa pun bisa **membaca lokasi kendaraan secara real-time** (subscribe `vehicle/#`) dan **mengirim data palsu**.
- Port `4356` menerima koneksi dari IMEI apa pun (tidak ada whitelist).
- Password VPS **jangan** disimpan di notes, cloud, atau repo. Gunakan password manager. Pertimbangkan login SSH dengan key dan matikan login password.

Rencana hardening:

```text
MQTT username/password + ACL per topic + TLS di port 8883
Whitelist IMEI di gps_server.py
SSH key-only login
```

---

## 13. Status & Roadmap

### Selesai ✅

- [x] VPS Rumahweb aktif dan SSH berhasil
- [x] Python environment dan GPS server
- [x] Koneksi TCP FMB125
- [x] Parser Codec 8 Extended (GPS)
- [x] Parser Codec 12 (RS232)
- [x] Mosquitto MQTT
- [x] GPS → MQTT
- [x] TPMS → RS232 → FMB125 → Python → MQTT
- [x] Android menerima MQTT
- [x] Pressure dan temperature terbaca, 8 ban berhasil dites

### Belum dikerjakan ⏳

Urutan yang disarankan:

| Tahap | Pekerjaan |
|---|---|
| **A** | 🟡 **NEXT:** refactor sudah dibuat sebagai `gps_server_v2.py` *(belum di-test, perlu deploy di VPS)*, lihat [bagian 10](#10-next-gps_server_v2py) |
| **B** | Service `systemd` untuk `gps_server.py` (auto-start dan auto-restart) |
| **C** | MQTT authentication, ACL, TLS, port 8883 |
| **D** | Penyimpanan database dan dashboard/web |
| **E** | Monitoring online/offline device (MQTT LWT / topic `vehicle/{IMEI}/status`) |
| — | Integrasi Android khusus TPMS |
| — | Multi-FMB125 / multi-vehicle (butuh tahap A dulu) |

---

## 14. Kalimat Kunci untuk Melanjutkan

Tempel kalimat ini saat membuka chat baru:

> **Lanjutkan project FMB125 → VPS → MQTT. VPS 202.10.47.206, Python `/root/gps_server.py`, FMB125 IMEI 352016700616766, TCP port 4356, Mosquitto port 1883. GPS sudah berhasil ke MQTT dan TPMS Codec 12 juga sudah berhasil ke topic `vehicle/352016700616766/tpms`. Refactor `gps_server_v2.py` sudah dibuat (lolos tes simulator, belum di-test di VPS, perlu deploy). Lihat README.md bagian 10 (NEXT) dan Roadmap.**
