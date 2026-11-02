package com.gpsaxius.monitor
import android.Manifest
import android.app.AlertDialog
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.eclipse.paho.client.mqttv3.IMqttActionListener
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.IMqttToken
import org.eclipse.paho.client.mqttv3.MqttAsyncClient
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttException
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import android.speech.tts.TextToSpeech
import android.widget.ArrayAdapter
import android.widget.Spinner

class MainActivity : AppCompatActivity() {

    private var mqttClient: MqttAsyncClient? = null

    private val mqttServer = "tcp://202.10.47.206:1883"
    private val gpsTopic = "vehicle/352016700616766/gps"
    private val tpmsTopic = "vehicle/352016700616766/tpms"

    private val backgroundColor = Color.rgb(15, 23, 34)
    private val secondaryColor = Color.rgb(153, 169, 188)
    private val greenColor = Color.rgb(51, 220, 170)
    private val redColor = Color.rgb(255, 100, 110)
    private val orangeColor = Color.rgb(255, 183, 77)

    private lateinit var statusText: TextView
    private lateinit var speedText: TextView
    private lateinit var satelliteText: TextView
    private lateinit var latitudeText: TextView
    private lateinit var longitudeText: TextView
    private lateinit var altitudeText: TextView
    private lateinit var angleText: TextView
    private lateinit var gpsTimeText: TextView
    private lateinit var gpsUpdateText: TextView
    private lateinit var tpmsUpdateText: TextView
    private lateinit var openMapsButton: Button
    private lateinit var alarmSettingsButton: Button

    private val tireRootViews = mutableMapOf<Int, View>()
    private val tireStatusViews = mutableMapOf<Int, TextView>()
    private val lastCriticalState = mutableMapOf<Int, Boolean>()

    private val alarmPrefs by lazy { getSharedPreferences("tpms_alarm_settings", MODE_PRIVATE) }
    private var minPressurePsi = 90.0
    private var maxPressurePsi = 120.0
    private var maxTemperatureC = 80.0

    private val tirePressureViews = mutableMapOf<Int, TextView>()
    private val tireTemperatureViews = mutableMapOf<Int, TextView>()

    private var latestLatitude: Double? = null
    private var latestLongitude: Double? = null
    private var gpsReceived = false
    private var tpmsReceived = false


    private lateinit var tts: TextToSpeech
    private var ttsReady = false


    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tts = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS

            if (ttsReady) {
                val result = tts.setLanguage(Locale("id", "ID"))
                ttsReady = result != TextToSpeech.LANG_MISSING_DATA &&
                        result != TextToSpeech.LANG_NOT_SUPPORTED

                tts.setSpeechRate(0.9f)
                tts.setPitch(1.0f)
            }
        }
        window.statusBarColor = backgroundColor
        window.navigationBarColor = backgroundColor
        window.decorView.systemUiVisibility = 0

        setContentView(R.layout.activity_main)
        loadAlarmSettings()
        createNotificationChannel()
        bindViews()
        requestNotificationPermissionIfNeeded()
        connectMqtt()
    }

    private fun bindViews() {
        statusText = findViewById(R.id.statusText)
        speedText = findViewById(R.id.speedText)
        satelliteText = findViewById(R.id.satelliteText)
        latitudeText = findViewById(R.id.latitudeText)
        longitudeText = findViewById(R.id.longitudeText)
        altitudeText = findViewById(R.id.altitudeText)
        angleText = findViewById(R.id.angleText)
        gpsTimeText = findViewById(R.id.gpsTimeText)
        gpsUpdateText = findViewById(R.id.gpsUpdateText)
        tpmsUpdateText = findViewById(R.id.tpmsUpdateText)
        openMapsButton = findViewById(R.id.openMapsButton)
        alarmSettingsButton = findViewById(R.id.alarmSettingsButton)

        alarmSettingsButton.setOnClickListener { showAlarmSettingsDialog() }

        openMapsButton.setOnClickListener {
            openVehicleLocation()
        }

        val tireRootIds = listOf(
            R.id.tire1, R.id.tire2, R.id.tire3, R.id.tire4,
            R.id.tire5, R.id.tire6, R.id.tire7, R.id.tire8
        )

        tireRootIds.forEachIndexed { index, rootId ->
            val number = index + 1
            val tireRoot = findViewById<View>(rootId)
            val label = tireRoot.findViewById<TextView>(R.id.tireLabel)
            val tireStatus = tireRoot.findViewById<TextView>(R.id.tireStatus)
            val pressure = tireRoot.findViewById<TextView>(R.id.tirePressure)
            val temperature = tireRoot.findViewById<TextView>(R.id.tireTemperature)

            label.text = "◉  Tire $number"
            tireRootViews[number] = tireRoot
            tireStatusViews[number] = tireStatus
            lastCriticalState[number] = false
            tirePressureViews[number] = pressure
            tireTemperatureViews[number] = temperature
        }
    }

    private fun connectMqtt() {
        try {
            val clientId = "AndroidGPSMonitor_${System.currentTimeMillis()}"

            mqttClient = MqttAsyncClient(mqttServer, clientId, null)

            mqttClient?.setCallback(
                object : MqttCallbackExtended {
                    override fun connectComplete(reconnect: Boolean, serverURI: String?) {
                        runOnUiThread {
                            statusText.text = if (reconnect) {
                                "●  MQTT TERHUBUNG KEMBALI"
                            } else {
                                "●  MQTT TERHUBUNG"
                            }
                            statusText.setTextColor(greenColor)
                        }
                        subscribeTopics()
                    }

                    override fun connectionLost(cause: Throwable?) {
                        runOnUiThread {
                            statusText.text = "●  MQTT TERPUTUS"
                            statusText.setTextColor(redColor)
                        }
                    }

                    override fun messageArrived(topic: String?, message: MqttMessage?) {
                        val payload = message?.toString() ?: ""
                        runOnUiThread {
                            when (topic) {
                                gpsTopic -> updateGps(payload)
                                tpmsTopic -> updateTpms(payload)
                            }
                        }
                    }

                    override fun deliveryComplete(token: IMqttDeliveryToken?) {
                        // Aplikasi hanya menerima data.
                    }
                }
            )

            val options = MqttConnectOptions().apply {
                isCleanSession = true
                connectionTimeout = 10
                keepAliveInterval = 30
                isAutomaticReconnect = true
            }

            statusText.text = "●  MENGHUBUNGKAN MQTT..."
            statusText.setTextColor(orangeColor)

            mqttClient?.connect(
                options,
                null,
                object : IMqttActionListener {
                    override fun onSuccess(asyncActionToken: IMqttToken?) {
                        // connectComplete menangani status dan subscribe.
                    }

                    override fun onFailure(
                        asyncActionToken: IMqttToken?,
                        exception: Throwable?
                    ) {
                        runOnUiThread {
                            statusText.text = "●  GAGAL TERHUBUNG MQTT"
                            statusText.setTextColor(redColor)
                        }
                    }
                }
            )
        } catch (e: Exception) {
            statusText.text = "●  MQTT ERROR: ${e.message}"
            statusText.setTextColor(redColor)
        }
    }

    private fun subscribeTopics() {
        try {
            mqttClient?.subscribe(
                arrayOf(gpsTopic, tpmsTopic),
                intArrayOf(0, 0),
                null,
                object : IMqttActionListener {
                    override fun onSuccess(asyncActionToken: IMqttToken?) {
                        runOnUiThread {
                            statusText.text = "●  MQTT TERHUBUNG • SUBSCRIBE AKTIF"
                            statusText.setTextColor(greenColor)
                        }
                    }

                    override fun onFailure(
                        asyncActionToken: IMqttToken?,
                        exception: Throwable?
                    ) {
                        runOnUiThread {
                            statusText.text = "●  GAGAL SUBSCRIBE"
                            statusText.setTextColor(redColor)
                        }
                    }
                }
            )
        } catch (e: MqttException) {
            runOnUiThread {
                statusText.text = "●  SUBSCRIBE ERROR"
                statusText.setTextColor(redColor)
            }
        }
    }

    private fun JSONObject.findValue(vararg names: String): String? {
        val keys = keys().asSequence().toList()
        for (name in names) {
            val key = keys.firstOrNull { it.equals(name, ignoreCase = true) }
                ?: continue
            val value = opt(key)
            if (value != null && value != JSONObject.NULL) return value.toString()
        }
        return null
    }

    private fun updateGps(payload: String) {
        try {
            val json = JSONObject(payload)

            val latitude = json.findValue("latitude", "lat")
            val longitude = json.findValue("longitude", "lon", "lng")
            val speed = json.findValue("speed", "speed_kmh")
            val satellites = json.findValue("satellites", "sats")
            val altitude = json.findValue("altitude", "alt")
            val angle = json.findValue("angle", "course", "heading")
            val timestamp = json.findValue("timestamp", "datetime", "time")

            val latValue = latitude?.toDoubleOrNull()
            val lonValue = longitude?.toDoubleOrNull()

            if (
                latValue != null &&
                lonValue != null &&
                latValue.isFinite() &&
                lonValue.isFinite() &&
                latValue in -90.0..90.0 &&
                lonValue in -180.0..180.0 &&
                (latValue != 0.0 || lonValue != 0.0)
            ) {
                latestLatitude = latValue
                latestLongitude = lonValue
                openMapsButton.isEnabled = true
                openMapsButton.alpha = 1f
            } else {
                latestLatitude = null
                latestLongitude = null
                openMapsButton.isEnabled = false
                openMapsButton.alpha = 0.5f
            }

            latitudeText.text = latitude ?: "--"
            longitudeText.text = longitude ?: "--"
            speedText.text = speed?.toDoubleOrNull()
                ?.let { String.format(Locale.US, "%.1f", it) } ?: "--"
            satelliteText.text = satellites ?: "--"
            altitudeText.text = altitude?.let { "$it m" } ?: "--"
            angleText.text = angle?.let { "$it°" } ?: "--"
            gpsTimeText.text = formatGpsTime(timestamp)
            gpsUpdateText.text = "Data GPS diterima: ${currentTime()}"

            gpsReceived = true
            updateStatusSummary()
        } catch (e: Exception) {
            gpsUpdateText.text = "Data GPS diterima, tetapi format JSON tidak dikenali."
        }
    }

    private fun openVehicleLocation() {
        val latitude = latestLatitude
        val longitude = latestLongitude

        if (latitude == null || longitude == null) {
            Toast.makeText(this, "Koordinat GPS belum tersedia.", Toast.LENGTH_SHORT).show()
            return
        }

        val mapsUri = Uri.parse("https://www.google.com/maps?q=$latitude,$longitude")
        val intent = Intent(Intent.ACTION_VIEW, mapsUri)

        try {
            startActivity(intent)
        } catch (_: Exception) {
            Toast.makeText(
                this,
                "Tidak dapat membuka Google Maps atau browser.",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private var lastBeepState = ""

    private fun updateTpms(payload: String) {
        try {
            val json = JSONObject(payload)
            val currentTireStates = mutableListOf<TireAlarmState>()
            var updated = 0

            for (tireNumber in 1..8) {
                val tire = json.optJSONObject("tire$tireNumber")
                    ?: continue

                val rawPressure = tire.optDouble(
                    "pressure_psi",
                    Double.NaN
                )
                val rawTemperature = tire.optDouble(
                    "temperature_c",
                    Double.NaN
                )

                val pressure = rawPressure.takeIf { it.isFinite() }
                val temperature = rawTemperature.takeIf { it.isFinite() }

                tirePressureViews[tireNumber]?.text =
                    pressure?.let {
                        String.format(Locale.US, "%.1f", it)
                    } ?: "--"

                tireTemperatureViews[tireNumber]?.text =
                    temperature?.let {
                        String.format(Locale.US, "%.1f °C", it)
                    } ?: "-- °C"

                val state = getTireAlarmState(pressure, temperature)

                currentTireStates.add(state)
                updateTireAppearance(tireNumber, state)

                val isCritical = state == TireAlarmState.CRITICAL
                val wasCritical = lastCriticalState[tireNumber] == true

                if (isCritical && !wasCritical) {
                    val reason = buildCriticalReason(pressure, temperature)
                    sendTireAlarmNotification(tireNumber, reason)
                }

                lastCriticalState[tireNumber] = isCritical
                updated++
            }

            if (updated > 0) {
                val adaBanCritical = currentTireStates.any {
                    it == TireAlarmState.CRITICAL
                }
                val adaBanWarning = currentTireStates.any {
                    it == TireAlarmState.WARNING
                }

                val beepState = when {
                    adaBanCritical -> "CRITICAL"
                    adaBanWarning -> "WARNING"
                    else -> "NORMAL"
                }

                if (beepState != lastBeepState) {
                    when (beepState) {
                        "CRITICAL" -> playAlarmBeep(2)
                        "WARNING" -> playAlarmBeep(1)
                    }
                    lastBeepState = beepState
                }

                tpmsReceived = true
                tpmsUpdateText.text =
                    "Data TPMS diterima: ${currentTime()} • $updated ban diperbarui"

                updateStatusSummary()
            } else {
                tpmsUpdateText.text =
                    "JSON diterima, tetapi data ban tidak ditemukan."
            }
        } catch (e: Exception) {
            tpmsUpdateText.text =
                "Gagal membaca JSON TPMS: ${e.message ?: "format tidak valid"}"
        }
    }

    private fun playAlarmBeep(count: Int) {
        if (!ttsReady) return

        val message = if (count >= 2) {
            "Bahaya! Kondisi ban kritis!"
        } else {
            "Peringatan! Periksa kondisi ban."
        }

        repeat(count) { index ->
            tts.speak(
                message,
                if (index == 0) TextToSpeech.QUEUE_FLUSH
                else TextToSpeech.QUEUE_ADD,
                null,
                "tpms_alarm_$index"
            )
        }
    }

    private enum class TireAlarmState { NORMAL, WARNING, CRITICAL, UNKNOWN }

    private fun getTireAlarmState(pressure: Double?, temperature: Double?): TireAlarmState {
        if (pressure == null || temperature == null || !pressure.isFinite() ||
            !temperature.isFinite() || pressure <= 0.0) {
            return TireAlarmState.UNKNOWN
        }
        if (pressure < minPressurePsi || pressure > maxPressurePsi || temperature >= maxTemperatureC) {
            return TireAlarmState.CRITICAL
        }
        if (pressure < minPressurePsi + 5.0 || pressure > maxPressurePsi - 5.0 ||
            temperature >= maxTemperatureC - 10.0) {
            return TireAlarmState.WARNING
        }
        return TireAlarmState.NORMAL
    }

    private fun updateTireAppearance(tireNumber: Int, state: TireAlarmState) {
        val root = tireRootViews[tireNumber] ?: return
        val status = tireStatusViews[tireNumber] ?: return
        val pressure = tirePressureViews[tireNumber]
        val temperature = tireTemperatureViews[tireNumber]
        when (state) {
            TireAlarmState.NORMAL -> {
                root.setBackgroundResource(R.drawable.bg_tire_normal)
                status.text = "● NORMAL"
                status.setTextColor(Color.rgb(51, 220, 170))
                pressure?.setTextColor(Color.WHITE)
                temperature?.setTextColor(Color.WHITE)
            }
            TireAlarmState.WARNING -> {
                root.setBackgroundResource(R.drawable.bg_tire_warning)
                status.text = "● PERINGATAN"
                status.setTextColor(Color.rgb(255, 193, 7))
                pressure?.setTextColor(Color.rgb(255, 193, 7))
                temperature?.setTextColor(Color.rgb(255, 193, 7))
            }
            TireAlarmState.CRITICAL -> {
                root.setBackgroundResource(R.drawable.bg_tire_critical)
                status.text = "● BAHAYA"
                status.setTextColor(Color.rgb(255, 100, 110))
                pressure?.setTextColor(Color.rgb(255, 100, 110))
                temperature?.setTextColor(Color.rgb(255, 100, 110))
            }
            TireAlarmState.UNKNOWN -> {
                root.setBackgroundResource(R.drawable.bg_card)
                status.text = "● DATA TIDAK VALID"
                status.setTextColor(secondaryColor)
                pressure?.setTextColor(secondaryColor)
                temperature?.setTextColor(secondaryColor)
            }
        }
    }

    private fun buildCriticalReason(pressure: Double?, temperature: Double?): String {
        val reasons = mutableListOf<String>()
        if (pressure != null && pressure < minPressurePsi) {
            reasons.add("tekanan rendah ${String.format(Locale.US, "%.1f", pressure)} PSI")
        }
        if (pressure != null && pressure > maxPressurePsi) {
            reasons.add("tekanan tinggi ${String.format(Locale.US, "%.1f", pressure)} PSI")
        }
        if (temperature != null && temperature >= maxTemperatureC) {
            reasons.add("temperatur ${String.format(Locale.US, "%.1f", temperature)} °C")
        }
        return reasons.joinToString(", ").ifBlank { "Nilai melewati batas alarm" }
    }

    private fun loadAlarmSettings() {
        minPressurePsi = alarmPrefs.getString("min_pressure", "90")?.toDoubleOrNull() ?: 90.0
        maxPressurePsi = alarmPrefs.getString("max_pressure", "120")?.toDoubleOrNull() ?: 120.0
        maxTemperatureC = alarmPrefs.getString("max_temperature", "80")?.toDoubleOrNull() ?: 80.0
    }

    private fun showAlarmSettingsDialog() {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 8, 48, 0)
        }

        fun addSetting(label: String, value: Double): EditText {
            val labelView = TextView(this).apply {
                text = label
                textSize = 14f
                setTextColor(android.graphics.Color.WHITE)
            }
            container.addView(labelView)

            val input = EditText(this).apply {
                setSingleLine(true)
                inputType = android.text.InputType.TYPE_CLASS_NUMBER or
                        android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
                setText(String.format(Locale.US, "%.1f", value))
                setTextColor(android.graphics.Color.WHITE)
                setHintTextColor(android.graphics.Color.GRAY)
            }
            container.addView(input)

            return input
        }

        val minInput = addSetting("Tekanan minimum (PSI)", minPressurePsi)
        val maxInput = addSetting("Tekanan maksimum (PSI)", maxPressurePsi)
        val tempInput = addSetting("Temperatur maksimum (°C)", maxTemperatureC)

        AlertDialog.Builder(this)
            .setTitle("Pengaturan Alarm TPMS")
            .setMessage("Nilai awal hanya contoh. Sesuaikan dengan rekomendasi tekanan ban kendaraan.")
            .setView(container)
            .setNegativeButton("Batal", null)
            .setPositiveButton("Simpan", null)
            .create().also { dialog ->
                dialog.setOnShowListener {
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                        val min = minInput.text.toString().trim().toDoubleOrNull()
                        val max = maxInput.text.toString().trim().toDoubleOrNull()
                        val temp = tempInput.text.toString().trim().toDoubleOrNull()
                        if (min == null || max == null || temp == null || min <= 0.0 || max <= min || temp <= 0.0) {
                            Toast.makeText(this, "Periksa nilai. Tekanan maksimum harus lebih besar dari minimum.", Toast.LENGTH_LONG).show()
                            return@setOnClickListener
                        }
                        minPressurePsi = min
                        maxPressurePsi = max
                        maxTemperatureC = temp
                        alarmPrefs.edit()
                            .putString("min_pressure", min.toString())
                            .putString("max_pressure", max.toString())
                            .putString("max_temperature", temp.toString())
                            .apply()
                        dialog.dismiss()
                        Toast.makeText(this, "Pengaturan alarm disimpan.", Toast.LENGTH_SHORT).show()
                    }
                }
                dialog.show()
            }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "tpms_alarm_channel",
                "Alarm TPMS",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Peringatan tekanan dan temperatur ban kendaraan"
            }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2201)
        }
    }

    private fun sendTireAlarmNotification(tireNumber: Int, reason: String) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return
        }
        val notification = NotificationCompat.Builder(this, "tpms_alarm_channel")
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("ALARM TPMS — Ban $tireNumber")
            .setContentText(reason)
            .setStyle(NotificationCompat.BigTextStyle().bigText("Ban $tireNumber: $reason. Periksa kondisi ban kendaraan."))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .build()
        getSystemService(NotificationManager::class.java).notify(100 + tireNumber, notification)
    }

    private fun formatGpsTime(value: String?): String {
        if (value.isNullOrBlank()) return "--"
        val number = value.toLongOrNull()

        if (number != null) {
            return try {
                val millis = if (number < 10_000_000_000L) number * 1000 else number
                SimpleDateFormat(
                    "dd-MM-yyyy HH:mm:ss",
                    Locale.getDefault()
                ).format(Date(millis))
            } catch (e: Exception) {
                value
            }
        }
        return value
    }

    private fun currentTime(): String {
        return SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
    }

    private fun updateStatusSummary() {
        if (gpsReceived && tpmsReceived) {
            statusText.text = "●  MQTT TERHUBUNG • GPS + TPMS AKTIF"
            statusText.setTextColor(greenColor)
        } else if (gpsReceived) {
            statusText.text = "●  MQTT TERHUBUNG • MENUNGGU TPMS"
            statusText.setTextColor(orangeColor)
        } else if (tpmsReceived) {
            statusText.text = "●  MQTT TERHUBUNG • MENUNGGU GPS"
            statusText.setTextColor(orangeColor)
        }
    }



    override fun onDestroy() {
        try {
            mqttClient?.setCallback(null)
            mqttClient?.disconnect()
            mqttClient?.close()
        } catch (_: Exception) {
            // Abaikan error saat activity ditutup.
        }
        super.onDestroy()
    }
}
