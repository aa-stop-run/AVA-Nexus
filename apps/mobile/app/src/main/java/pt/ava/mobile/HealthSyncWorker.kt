package pt.ava.mobile

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class HealthSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    companion object {
        const val TAG = "HealthSyncWorker"
        const val WORK_NAME = "ava_health_sync_periodic"
    }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val context = applicationContext
        Log.i(TAG, "Iniciando sincronização de métricas de saúde com o Hub AVA...")

        try {
            val healthManager = HealthConnectManager(context)
            val payload = healthManager.extrairMetricasHoje()

            val hubUrl = Config.getHubUrl(context)
            val token = Config.getDeviceToken(context)
            val endpoint = "$hubUrl/api/saude/sync/health-connect"

            val mediaType = "application/json; charset=utf-8".toMediaType()
            val requestBody = payload.toString().toRequestBody(mediaType)

            val request = Request.Builder()
                .url(endpoint)
                .addHeader("X-AVA-Device-Token", token)
                .post(requestBody)
                .build()

            val response = httpClient.newCall(request).execute()
            if (response.isSuccessful) {
                Log.i(TAG, "Métricas sincronizadas com sucesso no Hub: ${response.code}")
                Result.success()
            } else {
                Log.w(TAG, "Falha na sincronização com o Hub (HTTP ${response.code}): ${response.message}")
                if (response.code in 500..599 || response.code == 408) {
                    Result.retry()
                } else {
                    Result.failure()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Erro de rede ao sincronizar com o Hub AVA: ${e.message}", e)
            Result.retry()
        }
    }
}
