"""
gps_server_v2.py — FMB125 → MQTT (GPS + TPMS)

Versi refactor dari gps_server.py.
STATUS: BELUM DITES DI VPS / FMB125 ASLI (baru dites dengan simulator).

Perubahan dibanding v1:
  1. IMEI disimpan per koneksi (aman untuk banyak device sekaligus)
  2. Validasi preamble + CRC-16/IBM (paket rusak ditolak, device kirim ulang)
  3. Socket timeout (koneksi "hantu" ditutup otomatis)
  4. Buffer RS232 per koneksi (baris TPMS yang terpotong digabung dulu)
  5. TPMS jumlah ban dinamis (tidak harus 8)
  6. Payload GPS ditambah field "valid"
  7. Error saat parsing tidak memutus koneksi
  8. MQTT auto-reconnect, kompatibel paho-mqtt 1.x dan 2.x
  9. Log dengan waktu + IMEI

Topic MQTT dan port TIDAK berubah.
"""

import json
import logging
import socket
import struct
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


# =========================================================
# KONFIGURASI
# =========================================================

HOST = "0.0.0.0"
PORT = 4356

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_GPS = "vehicle/{imei}/gps"
MQTT_TOPIC_TPMS = "vehicle/{imei}/tpms"

# Koneksi ditutup jika tidak ada data selama N detik.
# FMB125 biasanya kirim data tiap beberapa detik s/d beberapa menit
# (tergantung setting Data Acquisition). Sesuaikan jika perlu.
SOCKET_TIMEOUT = 600

# Batas ukuran 1 paket (proteksi dari data aneh / bukan FMB125)
MAX_PACKET_SIZE = 64 * 1024

# Validasi CRC. Jika muncul banyak "[CRC] TIDAK COCOK" padahal
# device normal, set False sementara lalu laporkan.
CHECK_CRC = True

# RS232:
# True  = data dikumpulkan sampai ketemu newline (\n), baru diproses.
#         Aman untuk data yang terpotong, TAPI perangkat TPMS
#         WAJIB mengirim \r\n atau \n di akhir setiap baris.
# False = setiap paket Codec 12 langsung diproses (perilaku v1).
RS232_REQUIRE_NEWLINE = True
RS232_MAX_BUFFER = 4096

# Tampilkan RAW HEX setiap paket?
SHOW_RAW_HEX = False

# IO ID yang ingin ditampilkan di log, contoh: [239, 240, 21]
# IO yang pernah terlihat: 239, 240, 21, 200, 69, 181, 182,
# 66, 67, 68, 201, 241, 16
DISPLAY_IO_IDS = []


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gps")


# =========================================================
# MQTT
# =========================================================

mqtt_client = None


def init_mqtt():
    global mqtt_client

    try:
        # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        # paho-mqtt 1.x
        client = mqtt.Client()

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # connect_async + loop_start: jika broker belum siap,
    # server tetap jalan dan MQTT akan reconnect sendiri.
    client.connect_async(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    mqtt_client = client
    log.info(f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT}")


def publish(topic, payload):
    result = mqtt_client.publish(topic, json.dumps(payload), qos=0)

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        log.warning(f"[MQTT] Publish gagal (rc={result.rc}) → {topic}")
        return False

    return True


# =========================================================
# HELPER
# =========================================================

def read_exact(conn, length):
    buffer = b""

    while len(buffer) < length:
        chunk = conn.recv(length - len(buffer))

        if not chunk:
            return None

        buffer += chunk

    return buffer


def crc16_ibm(data):
    """CRC-16/IBM (ARC) — dipakai Teltonika untuk field CRC."""
    crc = 0x0000

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc


class Reader:
    """Pembaca data biner dengan cek panjang otomatis."""

    def __init__(self, data, offset=0):
        self.data = data
        self.offset = offset

    def take(self, n):
        if self.offset + n > len(self.data):
            raise ValueError(
                f"Data terpotong (butuh {n} byte di offset "
                f"{self.offset}, panjang {len(self.data)})"
            )

        chunk = self.data[self.offset:self.offset + n]
        self.offset += n
        return chunk

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack(">H", self.take(2))[0]

    def i16(self):
        return struct.unpack(">h", self.take(2))[0]

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]

    def i32(self):
        return struct.unpack(">i", self.take(4))[0]

    def u64(self):
        return struct.unpack(">Q", self.take(8))[0]


# =========================================================
# SESSION (1 per koneksi)
# =========================================================

class Session:

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.imei = None
        self.rs232_buffer = ""

    def tag(self):
        return f"[{self.imei or self.addr[0]}]"

    def info(self, msg):
        log.info(f"{self.tag()} {msg}")

    def warn(self, msg):
        log.warning(f"{self.tag()} {msg}")

    def send_ack(self, count):
        ack = struct.pack(">I", count)
        self.conn.sendall(ack)
        self.info(f"[ACK] {ack.hex(' ')} ({count})")


# =========================================================
# CODEC 8 EXTENDED (GPS)
# =========================================================

def parse_codec_8_extended(data, s):

    r = Reader(data)
    r.u8()  # codec id (0x8E)
    count = r.u8()

    s.info(f"[GPS] Codec 8 Extended, {count} record")

    for i in range(count):

        timestamp_ms = r.u64()

        if timestamp_ms > 0:
            dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            timestamp_text = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            timestamp_text = "0"

        r.u8()  # priority

        longitude = r.i32() / 10000000
        latitude = r.i32() / 10000000
        altitude = r.i16()
        angle = r.u16()
        satellites = r.u8()
        speed = r.u16()

        gps_data = {
            "timestamp": timestamp_text,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "angle": angle,
            "satellites": satellites,
            "speed": speed,
            "valid": satellites > 0,
        }

        s.info(
            f"[GPS] #{i + 1} {timestamp_text} "
            f"lat={latitude} lon={longitude} alt={altitude}m "
            f"angle={angle} sat={satellites} speed={speed}km/h"
            f"{'' if satellites > 0 else ' (TIDAK VALID)'}"
        )

        # ---------------- IO ----------------

        r.u16()  # event io id
        r.u16()  # total io

        io_values = {}

        for _ in range(r.u16()):
            io_id = r.u16()
            io_values[io_id] = r.u8()

        for _ in range(r.u16()):
            io_id = r.u16()
            io_values[io_id] = r.u16()

        for _ in range(r.u16()):
            io_id = r.u16()
            io_values[io_id] = r.u32()

        for _ in range(r.u16()):
            io_id = r.u16()
            io_values[io_id] = r.u64()

        for _ in range(r.u16()):
            io_id = r.u16()
            length = r.u16()
            io_values[io_id] = r.take(length).decode("utf-8", errors="replace")

        for io_id in DISPLAY_IO_IDS:
            value = io_values.get(io_id, "TIDAK ADA DI PACKET")
            s.info(f"[IO] {io_id}: {value}")

        # Publish setelah record berhasil di-parse lengkap
        topic = MQTT_TOPIC_GPS.format(imei=s.imei)
        if publish(topic, gps_data):
            s.info(f"[MQTT] GPS → {topic}")

    count_2 = r.u8()
    if count_2 != count:
        s.warn(f"[GPS] Number of Data 2 ({count_2}) != {count}")

    return count


# =========================================================
# CODEC 12 (RS232)
# =========================================================

def parse_codec_12(data, s):

    r = Reader(data)
    r.u8()  # codec id (0x0C)
    quantity = r.u8()

    for _ in range(quantity):

        msg_type = r.u8()
        size = r.u32()
        payload = r.take(size)

        text = payload.decode("utf-8", errors="replace")

        s.info(
            f"[RS232] type={msg_type} len={size} ascii={text!r}"
        )

        if SHOW_RAW_HEX:
            s.info(f"[RS232] hex={payload.hex(' ')}")

        handle_rs232_text(text, s)

    return quantity


def handle_rs232_text(text, s):

    if not RS232_REQUIRE_NEWLINE:
        process_rs232_line(text.strip(), s)
        return

    s.rs232_buffer += text

    while "\n" in s.rs232_buffer:
        line, s.rs232_buffer = s.rs232_buffer.split("\n", 1)
        line = line.strip()

        if line:
            process_rs232_line(line, s)

    if s.rs232_buffer:
        s.info(
            f"[RS232] Menunggu sisa data (belum ada newline): "
            f"{s.rs232_buffer!r}"
        )

    if len(s.rs232_buffer) > RS232_MAX_BUFFER:
        s.warn("[RS232] Buffer penuh tanpa newline, dibuang")
        s.rs232_buffer = ""


def process_rs232_line(line, s):

    if not line.startswith("TPMS;"):
        return

    tpms_data = parse_tpms(line, s)

    if tpms_data is None:
        return

    topic = MQTT_TOPIC_TPMS.format(imei=s.imei)

    if publish(topic, tpms_data):
        s.info(f"[MQTT] TPMS ({len(tpms_data)} ban) → {topic}")
        s.info(f"[TPMS] {json.dumps(tpms_data)}")


def parse_tpms(line, s):
    """
    TPMS;<ban>;<psi>;<celsius>;<ban>;<psi>;<celsius>;...
    Jumlah ban bebas (minimal 1).
    """

    parts = line.split(";")

    # Abaikan ";" di akhir baris jika ada
    if parts and parts[-1] == "":
        parts = parts[:-1]

    fields = parts[1:]

    if not fields or len(fields) % 3 != 0:
        s.warn(
            f"[TPMS] Format tidak sesuai: {len(fields)} field "
            f"(harus kelipatan 3)"
        )
        return None

    tpms_data = {}

    try:
        for t in range(0, len(fields), 3):
            tire = fields[t].strip()
            pressure = float(fields[t + 1])
            temperature = float(fields[t + 2])

            tpms_data[f"tire{tire}"] = {
                "pressure_psi": pressure,
                "temperature_c": temperature,
            }

    except ValueError as e:
        s.warn(f"[TPMS] Nilai tidak valid: {e}")
        return None

    return tpms_data


# =========================================================
# PACKET PROCESSOR
# =========================================================

def process_packet(data, s):
    """Return jumlah record untuk ACK."""

    if SHOW_RAW_HEX:
        s.info(f"[RAW] {data.hex(' ')}")

    codec_id = data[0]

    # Jumlah record ada di byte ke-2 untuk Codec 8E dan Codec 12.
    # Dipakai untuk ACK jika parsing gagal, supaya device tidak
    # mengirim ulang paket yang sama terus-menerus.
    count = data[1] if len(data) > 1 else 0

    try:

        if codec_id == 0x8E:
            return parse_codec_8_extended(data, s)

        if codec_id == 0x0C:
            return parse_codec_12(data, s)

        s.warn(f"[WARNING] Codec belum didukung: 0x{codec_id:02X}")

    except Exception as e:
        s.warn(f"[ERROR] Parse 0x{codec_id:02X} gagal: {e}")

    return count


# =========================================================
# CLIENT HANDLER
# =========================================================

def handle_client(s):

    conn = s.conn

    # ---------------- IMEI ----------------

    header = read_exact(conn, 2)
    if not header:
        s.warn("[ERROR] Gagal membaca panjang IMEI")
        return

    imei_length = struct.unpack(">H", header)[0]

    if not 1 <= imei_length <= 32:
        s.warn(f"[ERROR] Panjang IMEI tidak wajar: {imei_length}")
        return

    imei_data = read_exact(conn, imei_length)
    if not imei_data:
        s.warn("[ERROR] Gagal membaca IMEI")
        return

    imei = imei_data.decode("ascii", errors="replace")

    if not imei.isdigit():
        s.warn(f"[ERROR] IMEI tidak valid: {imei!r}")
        conn.sendall(b"\x00")
        return

    s.imei = imei
    conn.sendall(b"\x01")
    s.info(f"[IMEI] {imei} accepted")

    # ---------------- LOOP PAKET ----------------

    while True:

        preamble = read_exact(conn, 4)
        if not preamble:
            s.info("[INFO] Client disconnected")
            return

        if preamble != b"\x00\x00\x00\x00":
            s.warn(f"[ERROR] Preamble salah: {preamble.hex(' ')}")
            return

        size_data = read_exact(conn, 4)
        if not size_data:
            s.warn("[ERROR] Gagal membaca Data Size")
            return

        data_size = struct.unpack(">I", size_data)[0]

        if not 2 <= data_size <= MAX_PACKET_SIZE:
            s.warn(f"[ERROR] Data Size tidak wajar: {data_size}")
            return

        data = read_exact(conn, data_size)
        if not data:
            s.warn("[ERROR] Gagal membaca Data")
            return

        crc_data = read_exact(conn, 4)
        if not crc_data:
            s.warn("[ERROR] Gagal membaca CRC")
            return

        if CHECK_CRC:
            crc_received = struct.unpack(">I", crc_data)[0] & 0xFFFF
            crc_calc = crc16_ibm(data)

            if crc_received != crc_calc:
                s.warn(
                    f"[CRC] TIDAK COCOK (terima {crc_received:04X}, "
                    f"hitung {crc_calc:04X}) — paket ditolak"
                )
                # ACK 0 → device akan mengirim ulang
                s.send_ack(0)
                continue

        count = process_packet(data, s)
        s.send_ack(count)


def client_worker(conn, addr):

    conn.settimeout(SOCKET_TIMEOUT)
    s = Session(conn, addr)
    s.info(f"[INFO] Client connected: {addr[0]}:{addr[1]}")

    try:
        handle_client(s)

    except socket.timeout:
        s.warn(f"[INFO] Timeout {SOCKET_TIMEOUT}s tanpa data, koneksi ditutup")

    except (ConnectionResetError, BrokenPipeError) as e:
        s.warn(f"[INFO] Koneksi terputus: {e}")

    except Exception as e:
        s.warn(f"[ERROR] Client error: {e}")

    finally:
        conn.close()
        s.info("[INFO] Connection closed")


# =========================================================
# MAIN
# =========================================================

def main():

    init_mqtt()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)

    log.info(f"[SERVER] v2 listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()

        threading.Thread(
            target=client_worker,
            args=(conn, addr),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
