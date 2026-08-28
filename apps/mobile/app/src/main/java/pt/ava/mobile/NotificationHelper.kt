package pt.ava.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationManagerCompat

object NotificationHelper {

    const val CHANNEL_MEDICATION_ID = "ava_medication_channel"
    const val CHANNEL_RADAR_ID = "ava_radar_channel"

    fun createNotificationChannels(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // Canal 1: Medicação e Tomas (Alta Prioridade, Som e Vibração no Watch)
            val medChannel = NotificationChannel(
                CHANNEL_MEDICATION_ID,
                "Toma de Medicamentos (AVA Saúde)",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Lembretes e alarmes exatos para toma de medicação familiar"
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 500, 200, 500, 200, 800)
                setShowBadge(true)
            }
            notificationManager.createNotificationChannel(medChannel)

            // Canal 2: Radar e Briefing Proativo
            val radarChannel = NotificationChannel(
                CHANNEL_RADAR_ID,
                "Radar & Alertas AVA",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Briefing matinal, consultas médicas e alertas de prazos"
                enableVibration(true)
                setShowBadge(true)
            }
            notificationManager.createNotificationChannel(radarChannel)
        }
    }
}
