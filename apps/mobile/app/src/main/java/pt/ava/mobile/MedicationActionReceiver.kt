package pt.ava.mobile

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class MedicationActionReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_MEDICATION_TAKEN = "pt.ava.mobile.ACTION_MEDICATION_TAKEN"
        const val ACTION_MEDICATION_SNOOZE = "pt.ava.mobile.ACTION_MEDICATION_SNOOZE"
    }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    override fun onReceive(context: Context, intent: Intent) {
        val medId = intent.getIntExtra("medicamento_id", 0)
        val notificationId = intent.getIntExtra("notification_id", 0)

        // Cancel a notificação ativa
        if (notificationId != 0) {
            val notificationManager = NotificationManagerCompat.from(context)
            notificationManager.cancel(notificationId)
        }

        when (intent.action) {
            ACTION_MEDICATION_TAKEN -> {
                val nome = intent.getStringExtra("nome") ?: "Medicamento"
                Toast.makeText(context, "✔️ Toma de $nome registada!", Toast.LENGTH_SHORT).show()

                // Enviar requisição HTTP em background
                CoroutineScope(Dispatchers.IO).launch {
                    try {
                        val baseHubUrl = Config.getHubUrl(context)
                        val saudeUrl = baseHubUrl.replace(":8088", ":8083")
                        val endpoint = "$saudeUrl/api/saude/medicamentos/$medId/toma"

                        val json = JSONObject().apply {
                            put("registado_via", "mobile_notification")
                        }
                        val body = json.toString().toRequestBody("application/json; charset=utf-8".toMediaType())

                        val request = Request.Builder()
                            .url(endpoint)
                            .post(body)
                            .build()

                        httpClient.newCall(request).execute().close()
                    } catch (e: Exception) {
                        // Se falhar offline, a tomada foi confirmada pelo utilizador
                    }
                }
            }

            ACTION_MEDICATION_SNOOZE -> {
                val nome = intent.getStringExtra("nome") ?: "Medicamento"
                val dosagem = intent.getStringExtra("dosagem") ?: ""
                val titular = intent.getStringExtra("titular") ?: "aa-stop-run"
                val hora = intent.getStringExtra("hora") ?: ""
                val instrucoes = intent.getStringExtra("instrucoes") ?: ""

                Toast.makeText(context, "⏰ Toma de $nome adiada por 15 minutos.", Toast.LENGTH_SHORT).show()

                // Reagendar alarme para daqui a 15 minutos
                val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
                val triggerAtMillis = System.currentTimeMillis() + (15 * 60 * 1000)

                val snoozeIntent = Intent(context, MedicationAlarmReceiver::class.java).apply {
                    putExtra("medicamento_id", medId)
                    putExtra("nome", nome)
                    putExtra("dosagem", dosagem)
                    putExtra("titular", titular)
                    putExtra("hora", hora)
                    putExtra("instrucoes", instrucoes)
                }

                val snoozePendingIntent = PendingIntent.getBroadcast(
                    context,
                    (System.currentTimeMillis() % 100000).toInt(),
                    snoozeIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    alarmManager.setExactAndAllowWhileIdle(
                        AlarmManager.RTC_WAKEUP,
                        triggerAtMillis,
                        snoozePendingIntent
                    )
                } else {
                    alarmManager.setExact(
                        AlarmManager.RTC_WAKEUP,
                        triggerAtMillis,
                        snoozePendingIntent
                    )
                }
            }
        }
    }
}
