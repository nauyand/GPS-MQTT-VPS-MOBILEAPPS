#include <Arduino.h>
#include <SoftwareSerial.h>

//======================================
// D2 = RX dari TPMS
// D3 = TX ke GPS / MAX232
//======================================
SoftwareSerial TPMS(2, 3);

//======================================
// Data TPMS 1-8
//======================================
int rawPressure[9] = {0};
float pressurePSI[9] = {0};
float temperature[9] = {0};

//======================================
// MODE SIMULASI
// true  = tanpa TPMS, data random
// false = menggunakan TPMS asli
//======================================
bool SIMULATION_MODE = false;

//======================================
// Batas nilai yang diterima
//======================================
const float MIN_PRESSURE = 0.0;
const float MAX_PRESSURE = 150.0;

const float MIN_TEMPERATURE = 0.0;
const float MAX_TEMPERATURE = 100.0;

//======================================
// Parsing Data TPMS asli
//======================================
void parseTPMS(byte data[])
{
  byte sensorID = data[3];

  // Pastikan ID sensor berada pada 1-8
  if (sensorID < 1 || sensorID > 8)
    return;

  //==================================
  // PRESSURE dari data[4]
  //==================================
  int newRawPressure = data[4];

  float newPressure =
    ((newRawPressure * 5.5) - 99) * 0.145038;

  // Jika pressure valid, simpan nilainya
  if (newPressure >= MIN_PRESSURE &&
      newPressure <= MAX_PRESSURE)
  {
    rawPressure[sensorID] = newRawPressure;
    pressurePSI[sensorID] = newPressure;
  }
  else
  {
    // Nilai minus atau di luar batas tidak ditampilkan
    pressurePSI[sensorID] = 0.0;
    rawPressure[sensorID] = 0;
  }

  //==================================
  // TEMPERATURE dari data[5]
  //==================================
  float newTemperature = data[5] - 50.0;

  // Jika temperature valid, simpan nilainya
  if (newTemperature >= MIN_TEMPERATURE &&
      newTemperature <= MAX_TEMPERATURE)
  {
    temperature[sensorID] = newTemperature;
  }
  else
  {
    // Nilai minus atau di luar batas tidak ditampilkan
    temperature[sensorID] = 0.0;
  }
}

//======================================
// Membuat data random untuk simulasi
//======================================
void generateRandomData()
{
  for (int i = 1; i <= 8; i++)
  {
    // Pressure random 25.00 - 40.00 PSI
    pressurePSI[i] = random(2500, 4001) / 100.0;

    // Temperature random 20.00 - 40.00 C
    temperature[i] = random(2000, 4001) / 100.0;
  }
}

//======================================
// Mengambil pressure yang aman dikirim
//======================================
float getSafePressure(int sensorID)
{
  float value = pressurePSI[sensorID];

  if (value < MIN_PRESSURE ||
      value > MAX_PRESSURE)
  {
    return 0.0;
  }

  return value;
}

//======================================
// Mengambil temperature yang aman dikirim
//======================================
float getSafeTemperature(int sensorID)
{
  float value = temperature[sensorID];

  if (value < MIN_TEMPERATURE ||
      value > MAX_TEMPERATURE)
  {
    return 0.0;
  }

  return value;
}

//======================================
// Mengirim seluruh data TPMS
// Format tetap:
// TPMS;ID;Pressure;Temperature;...
//======================================
void sendTPMSData(Print &output)
{
  output.print("TPMS;");

  for (int i = 1; i <= 8; i++)
  {
    output.print(i);
    output.print(";");

    output.print(getSafePressure(i), 2);
    output.print(";");

    output.print(getSafeTemperature(i), 2);

    if (i < 8)
      output.print(";");
  }

  output.println();
}

//======================================
// Setup
//======================================
void setup()
{
  // Arduino -> GPS / MAX232
  TPMS.begin(19200);

  // Arduino -> Serial Monitor
  Serial.begin(19200);

  // Seed random untuk mode simulasi
  randomSeed(analogRead(A0));
}

//======================================
// Loop
//======================================
void loop()
{
  //----------------------------------
  // Menerima data TPMS asli
  //----------------------------------
  if (!SIMULATION_MODE)
  {
    if (TPMS.available() >= 2)
    {
      if (TPMS.read() == 0x55)
      {
        // Menunggu sisa frame
        while (TPMS.available() < 9)
        {
          // Tunggu data masuk
        }

        if (TPMS.read() == 0xAA)
        {
          byte data[10];

          data[0] = 0x55;
          data[1] = 0xAA;

          size_t received = TPMS.readBytes(&data[2], 8);

          if (received == 8)
          {
            parseTPMS(data);
          }
        }
      }
    }
  }

  //----------------------------------
  // Kirim data setiap 1500 ms
  //----------------------------------
  static unsigned long timer = 0;

  if (millis() - timer >= 1500)
  {
    timer = millis();

    //==================================
    // MODE SIMULASI
    //==================================
    if (SIMULATION_MODE)
    {
      generateRandomData();
    }

    //==================================
    // Kirim ke GPS / MAX232
    //==================================
    sendTPMSData(TPMS);

    //==================================
    // Kirim ke Serial Monitor
    //==================================
    sendTPMSData(Serial);
  }
}