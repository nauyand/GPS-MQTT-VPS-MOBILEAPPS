import socket
import threading
import struct
from datetime import datetime, timezone
import json
import paho.mqtt.client as mqtt

# =========================================================
# CONFIGURATION
# =========================================================

HOST = "0.0.0.0"
PORT = 4356

# =========================================================
# MQTT CONFIGURATION
# =========================================================

MQTT_HOST = "localhost"
MQTT_PORT = 1883

MQTT_TOPIC_GPS = "vehicle/{}/gps"
CURRENT_IMEI = "unknown"

mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
mqtt_client.loop_start()


# Tampilkan RAW HEX packet?
# True  = tampilkan
# False = sembunyikan
SHOW_RAW_HEX = False


# =========================================================
# PILIH IO ID YANG INGIN DITAMPILKAN
# =========================================================
#
# Contoh:
# DISPLAY_IO_IDS = [239, 240, 21]
#
# Jika tidak ingin menampilkan IO:
# DISPLAY_IO_IDS = []
#
# Berdasarkan data FMB125 kamu sebelumnya:
# 239, 240, 21, 200, 69, 181, 182,
# 66, 67, 68, 201, 241, 16
#
# Tinggal masukkan ID yang ingin ditampilkan.

DISPLAY_IO_IDS = [
    # 239,
    # 240,
    # 21,
]


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


def print_hex(data):
    return data.hex(" ")


# =========================================================
# CODEC 8 EXTENDED
# =========================================================

def parse_codec_8_extended(data, conn):

    if len(data) < 2:
        print("[ERROR] Packet terlalu pendek")
        return

    codec_id = data[0]
    count = data[1]

    if codec_id != 0x8E:
        print("[ERROR] Bukan Codec 8 Extended")
        return

    print("\n========================================")
    print("[GPS] CODEC 8 EXTENDED")
    print("========================================")

    print(f"[GPS] Number of records: {count}")

    offset = 2

    for i in range(count):

        print("\n----------------------------------------")
        print(f"[GPS] RECORD {i + 1}")
        print("----------------------------------------")

        # =================================================
        # TIMESTAMP
        # =================================================

        timestamp_ms = struct.unpack(
            ">Q",
            data[offset:offset + 8]
        )[0]

        offset += 8

        if timestamp_ms > 0:

            dt = datetime.fromtimestamp(
                timestamp_ms / 1000,
                tz=timezone.utc
            )

            timestamp_text = dt.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )

        else:

            timestamp_text = "0"

        # =================================================
        # PRIORITY
        # =================================================

        priority = data[offset]
        offset += 1

        # =================================================
        # GPS
        # =================================================

        longitude_raw = struct.unpack(
            ">i",
            data[offset:offset + 4]
        )[0]

        longitude = longitude_raw / 10000000

        offset += 4


        latitude_raw = struct.unpack(
            ">i",
            data[offset:offset + 4]
        )[0]

        latitude = latitude_raw / 10000000

        offset += 4


        altitude = struct.unpack(
            ">h",
            data[offset:offset + 2]
        )[0]

        offset += 2


        angle = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        satellites = data[offset]

        offset += 1


        speed = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        # =================================================
        # OUTPUT GPS UTAMA
        # =================================================

        print(f"Timestamp : {timestamp_text}")
        print(f"Latitude  : {latitude}")
        print(f"Longitude : {longitude}")
        print(f"Altitude  : {altitude} m")
        print(f"Angle     : {angle} °")
        print(f"Satellites: {satellites}")
        print(f"Speed     : {speed} km/h")

        # =================================================
        # MQTT GPS
        # =================================================

        gps_data = {
            "timestamp": timestamp_text,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "angle": angle,
            "satellites": satellites,
            "speed": speed
        }

        mqtt_topic = MQTT_TOPIC_GPS.format(CURRENT_IMEI)

        mqtt_client.publish(
            mqtt_topic,
            json.dumps(gps_data),
            qos=0
        )

        print(f"[MQTT] GPS published → {mqtt_topic}")

        # =================================================
        # IO
        # =================================================

        event_id = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        total_io = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        # Dictionary untuk menyimpan IO
        io_values = {}


        # =================================================
        # IO 1 BYTE
        # =================================================

        count_1b = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        for _ in range(count_1b):

            io_id = struct.unpack(
                ">H",
                data[offset:offset + 2]
            )[0]

            value = data[offset + 2]

            offset += 3

            io_values[io_id] = value


        # =================================================
        # IO 2 BYTE
        # =================================================

        count_2b = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        for _ in range(count_2b):

            io_id = struct.unpack(
                ">H",
                data[offset:offset + 2]
            )[0]

            value = struct.unpack(
                ">H",
                data[offset + 2:offset + 4]
            )[0]

            offset += 4

            io_values[io_id] = value


        # =================================================
        # IO 4 BYTE
        # =================================================

        count_4b = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        for _ in range(count_4b):

            io_id = struct.unpack(
                ">H",
                data[offset:offset + 2]
            )[0]

            value = struct.unpack(
                ">I",
                data[offset + 2:offset + 6]
            )[0]

            offset += 6

            io_values[io_id] = value


        # =================================================
        # IO 8 BYTE
        # =================================================

        count_8b = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        for _ in range(count_8b):

            io_id = struct.unpack(
                ">H",
                data[offset:offset + 2]
            )[0]

            value = struct.unpack(
                ">Q",
                data[offset + 2:offset + 10]
            )[0]

            offset += 10

            io_values[io_id] = value


        # =================================================
        # IO NX
        # =================================================

        count_nx = struct.unpack(
            ">H",
            data[offset:offset + 2]
        )[0]

        offset += 2


        for _ in range(count_nx):

            io_id = struct.unpack(
                ">H",
                data[offset:offset + 2]
            )[0]

            length = struct.unpack(
                ">H",
                data[offset + 2:offset + 4]
            )[0]

            offset += 4

            value = data[
                offset:
                offset + length
            ]

            offset += length

            try:

                value_decoded = value.decode(
                    "utf-8",
                    errors="replace"
                )

            except Exception:

                value_decoded = repr(value)


            io_values[io_id] = value_decoded


        # =================================================
        # TAMPILKAN IO YANG DIPILIH SAJA
        # =================================================

        if DISPLAY_IO_IDS:

            print("\n[IO] Selected IO:")

            for io_id in DISPLAY_IO_IDS:

                if io_id in io_values:

                    print(
                        f"IO ID {io_id}: "
                        f"{io_values[io_id]}"
                    )

                else:

                    print(
                        f"IO ID {io_id}: "
                        f"TIDAK ADA DI PACKET"
                    )


    # =====================================================
    # NUMBER OF DATA 2
    # =====================================================

    if offset < len(data):

        number_of_data_2 = data[offset]

        print(
            f"\n[INFO] Number of Data 2: "
            f"{number_of_data_2}"
        )

        if number_of_data_2 == count:

            print(
                "[INFO] Packet record count valid"
            )

        else:

            print(
                "[WARNING] Number of Data 2 "
                "tidak sama dengan Number of records"
            )


    # =====================================================
    # ACK
    # =====================================================

    ack = struct.pack(
        ">I",
        count
    )

    conn.sendall(ack)

    print(
        f"[ACK] Sent: "
        f"{ack.hex(' ')} "
        f"({count} record)"
    )


# =========================================================
# CODEC 12 - RS232 TCP ASCII
# =========================================================

def parse_codec_12(data, conn):

    print("\n========================================")
    print("[RS232] CODEC 12 TERDETEKSI")
    print("========================================")


    if len(data) < 2:

        print(
            "[ERROR] Packet Codec 12 terlalu pendek"
        )

        return


    codec_id = data[0]


    if codec_id != 0x0C:

        print(
            "[ERROR] Bukan Codec 12"
        )

        return


    quantity_1 = data[1]

    print(
        f"[RS232] Quantity 1 : "
        f"{quantity_1}"
    )


    offset = 2


    for i in range(quantity_1):

        if offset + 5 > len(data):

            print(
                "[ERROR] Struktur Codec 12 "
                "tidak lengkap"
            )

            return


        command_type = data[offset]

        offset += 1


        command_size = struct.unpack(
            ">I",
            data[offset:offset + 4]
        )[0]

        offset += 4


        payload = data[
            offset:
            offset + command_size
        ]

        offset += command_size


        print(
            f"[RS232] Message Type : "
            f"{command_type}"
        )

        print(
            f"[RS232] Data Length  : "
            f"{command_size}"
        )

        print(
            f"[RS232] HEX          : "
            f"{payload.hex(' ')}"
        )

        try:

            text = payload.decode(
                "utf-8",
                errors="replace"
            )

            print(
                f"[RS232] ASCII        : "
                f"{text!r}"
            )

        except Exception as e:

            print(
                f"[RS232] ASCII decode error: "
                f"{e}"
            )


        # =====================================================
        # TPMS PARSER
        # =====================================================

        if text.startswith("TPMS;"):

            try:

                parts = text.strip().split(";")

                # TPMS;1;pressure;temperature;2;pressure;temperature;...
                if len(parts) != 25:

                    print(
                        f"[TPMS] Format tidak sesuai. "
                        f"Jumlah data: {len(parts)}"
                    )

                else:

                    tpms_data = {}

                    for i in range(8):

                        index = 1 + (i * 3)

                        tire_number = parts[index]
                        pressure = float(parts[index + 1])
                        temperature = float(parts[index + 2])

                        tpms_data[f"tire{tire_number}"] = {
                            "pressure_psi": pressure,
                            "temperature_c": temperature
                        }


                    mqtt_topic = (
                        f"vehicle/{CURRENT_IMEI}/tpms"
                    )


                    mqtt_client.publish(
                        mqtt_topic,
                        json.dumps(tpms_data),
                        qos=0
                    )


                    print(
                        f"[MQTT] TPMS published → "
                        f"{mqtt_topic}"
                    )


                    print(
                        f"[TPMS] "
                        f"{json.dumps(tpms_data)}"
                    )


            except Exception as e:

                print(
                    f"[TPMS] Parse error: "
                    f"{e}"
                )

    # =====================================================
    # QUANTITY 2
    # =====================================================

    if offset < len(data):

        quantity_2 = data[offset]

        print(
            f"[RS232] Quantity 2 : "
            f"{quantity_2}"
        )


    # =====================================================
    # ACK
    # =====================================================

    ack = struct.pack(
        ">I",
        quantity_1
    )

    conn.sendall(ack)

    print(
        f"[ACK] Codec 12 ACK: "
        f"{ack.hex(' ')}"
    )


# =========================================================
# PACKET PROCESSOR
# =========================================================

def process_packet(packet, conn):

    if not packet:

        return


    print("\n========================================")
    print(
        f"[PACKET] "
        f"{len(packet)} bytes"
    )
    print("========================================")


    if SHOW_RAW_HEX:

        print(
            "[RAW]",
            packet.hex(" ")
        )


    codec_id = packet[0]


    print(
        f"[INFO] Codec ID: "
        f"0x{codec_id:02X}"
    )


    if codec_id == 0x8E:

        parse_codec_8_extended(
            packet,
            conn
        )


    elif codec_id == 0x0C:

        parse_codec_12(
            packet,
            conn
        )


    else:

        print(
            f"[WARNING] Codec belum didukung: "
            f"0x{codec_id:02X}"
        )


# =========================================================
# CLIENT HANDLER
# =========================================================

def handle_client(conn, addr):

    print("\n========================================")
    print(
        f"[INFO] Client connected: "
        f"{addr}"
    )
    print("========================================")


    # =====================================================
    # BACA IMEI
    # =====================================================

    imei_length_data = read_exact(
        conn,
        2
    )


    if not imei_length_data:

        print(
            "[ERROR] Gagal membaca panjang IMEI"
        )

        return


    imei_length = struct.unpack(
        ">H",
        imei_length_data
    )[0]


    imei_data = read_exact(
        conn,
        imei_length
    )


    if not imei_data:

        print(
            "[ERROR] Gagal membaca IMEI"
        )

        return


    imei = imei_data.decode(
        "ascii",
        errors="replace"
    )

    global CURRENT_IMEI
    CURRENT_IMEI = imei
    print(
        f"[IMEI] {imei}"
    )


    # =====================================================
    # ACK IMEI
    # =====================================================

    conn.sendall(
        b"\x01"
    )


    print(
        "[ACK] IMEI accepted"
    )


    # =====================================================
    # LOOP PACKET
    # =====================================================

    while True:

        # -------------------------------------------------
        # PREAMBLE
        # -------------------------------------------------

        preamble = read_exact(
            conn,
            4
        )


        if not preamble:

            print(
                "[INFO] Client disconnected"
            )

            break


        # -------------------------------------------------
        # DATA SIZE
        # -------------------------------------------------

        data_size_data = read_exact(
            conn,
            4
        )


        if not data_size_data:

            print(
                "[ERROR] Gagal membaca Data Size"
            )

            break


        data_size = struct.unpack(
            ">I",
            data_size_data
        )[0]


        print(
            f"\n[INFO] Data Size: "
            f"{data_size} bytes"
        )


        # -------------------------------------------------
        # DATA
        # -------------------------------------------------

        data = read_exact(
            conn,
            data_size
        )


        if not data:

            print(
                "[ERROR] Gagal membaca Data"
            )

            break


        # -------------------------------------------------
        # CRC
        # -------------------------------------------------

        crc = read_exact(
            conn,
            4
        )


        if not crc:

            print(
                "[ERROR] Gagal membaca CRC"
            )

            break


        # -------------------------------------------------
        # PROCESS
        # -------------------------------------------------

        process_packet(
            data,
            conn
        )


# =========================================================
# MAIN SERVER
# =========================================================

def main():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )


    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )


    server.bind(
        (
            HOST,
            PORT
        )
    )


    server.listen(10)


    print(
        f"[SERVER] Listening on "
        f"{HOST}:{PORT}"
    )


    while True:
        conn, addr = server.accept()

        worker = threading.Thread(
            target=client_worker,
            args=(conn, addr),
            daemon=True
        )
        worker.start()


def client_worker(conn, addr):
    try:
        handle_client(conn, addr)

    except Exception as e:
        print(f"[ERROR] Client error {addr}: {e}")

    finally:
        conn.close()
        print(f"[INFO] Connection closed: {addr}")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

        main()
