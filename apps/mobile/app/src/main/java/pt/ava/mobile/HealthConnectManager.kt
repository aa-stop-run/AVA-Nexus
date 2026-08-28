package pt.ava.mobile

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit

class HealthConnectManager(private val context: Context) {

    val healthConnectClient: HealthConnectClient? by lazy {
        if (HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectClient.getOrCreate(context)
        } else {
            null
        }
    }

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class)
    )

    suspend fun hasAllPermissions(): Boolean {
        val client = healthConnectClient ?: return false
        val granted = client.permissionController.getGrantedPermissions()
        return granted.containsAll(requiredPermissions)
    }

    suspend fun extrairMetricasHoje(): JSONObject {
        val payload = JSONObject()
        val hoje = LocalDate.now()
        val titular = Config.getTitular(context)

        payload.put("device_id", "galaxy-watch-8-mobile")
        payload.put("titular", titular)
        payload.put("data_referencia", hoje.toString())
        payload.put("gerado_em", Instant.now().toString())

        val client = healthConnectClient
        if (client == null || !hasAllPermissions()) {
            return payload
        }

        val zone = ZoneId.systemDefault()
        val inicioDoDia = hoje.atStartOfDay(zone).toInstant()
        val agora = Instant.now()
        val ultimas24h = agora.minus(24, ChronoUnit.HOURS)

        // 1. Passos do dia
        try {
            val stepsRequest = ReadRecordsRequest(
                recordType = StepsRecord::class,
                timeRangeFilter = TimeRangeFilter.between(inicioDoDia, agora)
            )
            val stepsResponse = client.readRecords(stepsRequest)
            val totalPassos = stepsResponse.records.sumOf { it.count }
            val atividade = JSONObject().apply {
                put("passos", totalPassos)
            }
            payload.put("atividade", atividade)
        } catch (_: Exception) {}

        // 2. Sono das últimas 24 horas (noite anterior)
        try {
            val sleepRequest = ReadRecordsRequest(
                recordType = SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(ultimas24h, agora)
            )
            val sleepResponse = client.readRecords(sleepRequest)
            val ultimaSessao = sleepResponse.records.maxByOrNull { it.endTime }

            if (ultimaSessao != null) {
                val duracaoMinutos = ChronoUnit.MINUTES.between(ultimaSessao.startTime, ultimaSessao.endTime)
                val sonoObj = JSONObject().apply {
                    put("minutos_total", duracaoMinutos)
                    put("hora_inicio", ultimaSessao.startTime.toString())
                    put("hora_fim", ultimaSessao.endTime.toString())

                    // Fases do sono se disponíveis
                    val fases = JSONObject()
                    var profundo = 0L
                    var rem = 0L
                    var leve = 0L
                    var acordado = 0L

                    for (stage in ultimaSessao.stages) {
                        val stageMin = ChronoUnit.MINUTES.between(stage.startTime, stage.endTime)
                        when (stage.stage) {
                            SleepSessionRecord.STAGE_TYPE_DEEP -> profundo += stageMin
                            SleepSessionRecord.STAGE_TYPE_REM -> rem += stageMin
                            SleepSessionRecord.STAGE_TYPE_LIGHT -> leve += stageMin
                            SleepSessionRecord.STAGE_TYPE_AWAKE -> acordado += stageMin
                        }
                    }

                    fases.put("profundo_minutos", profundo)
                    fases.put("rem_minutos", rem)
                    fases.put("leve_minutos", leve)
                    fases.put("acordado_minutos", acordado)
                    put("fases", fases)

                    // Cálculo heurístico de score se não fornecido
                    val score = ((duracaoMinutos.coerceIn(0, 480).toDouble() / 480.0) * 100).toInt()
                    put("score", score)
                }
                payload.put("sono", sonoObj)
            }
        } catch (_: Exception) {}

        // 3. Frequência Cardíaca e Repouso
        try {
            val cardioObj = JSONObject()

            // Repouso
            val restingRequest = ReadRecordsRequest(
                recordType = RestingHeartRateRecord::class,
                timeRangeFilter = TimeRangeFilter.between(ultimas24h, agora)
            )
            val restingResponse = client.readRecords(restingRequest)
            val ultimoRepouso = restingResponse.records.lastOrNull()?.beatsPerMinute
            if (ultimoRepouso != null) {
                cardioObj.put("bpm_repouso", ultimoRepouso)
            }

            // BPM geral
            val hrRequest = ReadRecordsRequest(
                recordType = HeartRateRecord::class,
                timeRangeFilter = TimeRangeFilter.between(ultimas24h, agora)
            )
            val hrResponse = client.readRecords(hrRequest)
            val todosBpm = hrResponse.records.flatMap { it.samples }.map { it.beatsPerMinute }
            if (todosBpm.isNotEmpty()) {
                cardioObj.put("bpm_medio", todosBpm.average().toInt())
                cardioObj.put("bpm_min", todosBpm.minOrNull() ?: 0)
                cardioObj.put("bpm_max", todosBpm.maxOrNull() ?: 0)
            }

            // HRV
            val hrvRequest = ReadRecordsRequest(
                recordType = HeartRateVariabilityRmssdRecord::class,
                timeRangeFilter = TimeRangeFilter.between(ultimas24h, agora)
            )
            val hrvResponse = client.readRecords(hrvRequest)
            val ultimoHrv = hrvResponse.records.lastOrNull()?.heartRateVariabilityMillis
            if (ultimoHrv != null) {
                cardioObj.put("hrv_rmssd_ms", ultimoHrv)
            }

            payload.put("cardiovascular", cardioObj)
        } catch (_: Exception) {}

        return payload
    }
}
