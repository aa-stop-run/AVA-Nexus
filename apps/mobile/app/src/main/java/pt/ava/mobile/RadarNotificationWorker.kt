package pt.ava.mobile

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.util.concurrent.TimeUnit

class RadarNotificationWorker(
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
            val endpoint = "$saudeUrl/api/saude/medicamentos/alertas-stock"

            val request = Request.Builder()
                .url(endpoint)
                .get()
                .build()

            val response = httpClient.newCall(request).execute()
            if (response.isSuccessful) {
                val bodyStr = response.body?.string() ?: "[]"
                val array = JSONArray(bodyStr)

                if (array.length() > 0) {
                    val intentOpen = Intent(context, MainActivity::class.java).apply {
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                    }
                    val pIntentOpen = PendingIntent.getActivity(
                        context,
                        101,
                        intentOpen,
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                    )

                    val primeiro = array.getJSONObject(0)
                    val nome = primeiro.getString("nome")
                    val titular = primeiro.getString("titular")
                    val stock = primeiro.getInt("stock_atual")
                    val dias = primeiro.getInt("dias_autonomia")

                    val titulo = "⚠️ Radar de Saúde: Low Stock de Medicação"
                    val texto = if (array.length() == 1) {
                        "Restam apenas $stock pills de $nome ($titular) (~$dias dias). Solicitar receita médica."
                    } else {
                        "Existem ${array.length()} medicamentos com stock crítico (ex: $nome para $titular). Solicitar receitas."
                    }

                    val builder = NotificationCompat.Builder(context, NotificationHelper.CHANNEL_RADAR_ID)
                        .setSmallIcon(R.mipmap.ic_launcher)
                        .setContentTitle(titulo)
                        .setContentText(texto)
                        .setStyle(NotificationCompat.BigTextStyle().bigText(texto))
                        .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                        .setAutoCancel(true)
                        .setContentIntent(pIntentOpen)

                    try {
                        val notificationManager = NotificationManagerCompat.from(context)
                        notificationManager.notify(9001, builder.build())
                    } catch (e: SecurityException) {
                        // Sem permissão de notificação
                    }
                }
            }

            Result.success()
        } catch (e: Exception) {
            Log.e("RadarNotificationWorker", "Erro ao verificar alertas de radar: ${e.message}", e)
            Result.retry()
        }
    }
}
