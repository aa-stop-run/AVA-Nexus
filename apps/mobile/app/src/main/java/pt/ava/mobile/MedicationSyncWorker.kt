package pt.ava.mobile

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit

class MedicationSyncWorker(
    private val context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result {
        return try {
            val baseHubUrl = Config.getHubUrl(context)
            val saudeUrl = baseHubUrl.replace(":8088", ":8083")
            val endpoint = "$saudeUrl/api/saude/medicamentos/schedule-sync?dias=7"

            val request = Request.Builder()
                .url(endpoint)
                .get()
                .build()

            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) {
                Log.w("MedicationSyncWorker", "Erro ao obter schedule-sync: ${response.code}")
                return Result.retry()
            }

            val bodyStr = response.body?.string() ?: "[]"
            val array = JSONArray(bodyStr)
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

            val isoFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }

            val now = System.currentTimeMillis()

            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                val medId = item.getInt("medicamento_id")
                val nome = item.getString("nome")
                val dosagem = item.getString("dosagem")
                val titular = item.getString("titular")
                val hora = item.getString("hora")
                val dtStr = item.getString("data_hora_prevista")
                val instrucoes = item.optString("instrucoes", "")

                // Parse da data ISO
                val cleanDateStr = if (dtStr.contains("+")) dtStr.substringBefore("+") else if (dtStr.endsWith("Z")) dtStr.dropLast(1) else dtStr
                val date = isoFormat.parse(cleanDateStr)
                if (date != null && date.time > now) {
                    val requestCode = (medId * 1000 + (date.time / 60000 % 10000)).toInt()

                    val intent = Intent(context, MedicationAlarmReceiver::class.java).apply {
                        putExtra("medicamento_id", medId)
                        putExtra("nome", nome)
                        putExtra("dosagem", dosagem)
                        putExtra("titular", titular)
                        putExtra("hora", hora)
                        putExtra("instrucoes", instrucoes)
                    }

                    val pendingIntent = PendingIntent.getBroadcast(
                        context,
                        requestCode,
                        intent,
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                    )

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        alarmManager.setExactAndAllowWhileIdle(
                            AlarmManager.RTC_WAKEUP,
                            date.time,
                            pendingIntent
                        )
                    } else {
                        alarmManager.setExact(
                            AlarmManager.RTC_WAKEUP,
                            date.time,
                            pendingIntent
                        )
                    }
                }
            }

            Log.i("MedicationSyncWorker", "Sincronizados ${array.length()} alarmes de medicação com sucesso.")
            Result.success()
        } catch (e: Exception) {
            Log.e("MedicationSyncWorker", "Falha na sincronização de alarmes: ${e.message}", e)
            Result.retry()
        }
    }
}
