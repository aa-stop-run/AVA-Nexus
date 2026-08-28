package pt.ava.mobile

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

class MedicationAlarmReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val medId = intent.getIntExtra("medicamento_id", 0)
        val nome = intent.getStringExtra("nome") ?: "Medicamento"
        val dosagem = intent.getStringExtra("dosagem") ?: ""
        val titular = intent.getStringExtra("titular") ?: "aa-stop-run"
        val hora = intent.getStringExtra("hora") ?: ""
        val instrucoes = intent.getStringExtra("instrucoes") ?: ""

        val notificationId = (10000 + medId * 100 + (System.currentTimeMillis() % 100)).toInt()

        // 1. Intent para Ação "✔️ Taken"
        val intentTaken = Intent(context, MedicationActionReceiver::class.java).apply {
            action = MedicationActionReceiver.ACTION_MEDICATION_TAKEN
            putExtra("medicamento_id", medId)
            putExtra("nome", nome)
            putExtra("notification_id", notificationId)
        }
        val pIntentTaken = PendingIntent.getBroadcast(
            context,
            notificationId * 2,
            intentTaken,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 2. Intent para Ação "⏰ Snooze 15m"
        val intentAdiar = Intent(context, MedicationActionReceiver::class.java).apply {
            action = MedicationActionReceiver.ACTION_MEDICATION_SNOOZE
            putExtra("medicamento_id", medId)
            putExtra("nome", nome)
            putExtra("dosagem", dosagem)
            putExtra("titular", titular)
            putExtra("hora", hora)
            putExtra("instrucoes", instrucoes)
            putExtra("notification_id", notificationId)
        }
        val pIntentAdiar = PendingIntent.getBroadcast(
            context,
            notificationId * 2 + 1,
            intentAdiar,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // 3. Intent para Abrir a App ao tocar na notificação
        val intentOpen = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pIntentOpen = PendingIntent.getActivity(
            context,
            0,
            intentOpen,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val desc = if (instrucoes.isNotBlank()) "$dosagem • $instrucoes" else "$dosagem • Hora programada: $hora"

        val builder = NotificationCompat.Builder(context, NotificationHelper.CHANNEL_MEDICATION_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("💊 Toma de Medicação: $nome ($titular)")
            .setContentText(desc)
            .setStyle(NotificationCompat.BigTextStyle().bigText("Está na hora da toma de $nome ($dosagem) para $titular.\n$desc"))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .setContentIntent(pIntentOpen)
            .addAction(android.R.drawable.ic_menu_save, "✔️ Taken", pIntentTaken)
            .addAction(android.R.drawable.ic_lock_idle_alarm, "⏰ Snooze 15m", pIntentAdiar)

        try {
            val notificationManager = NotificationManagerCompat.from(context)
            notificationManager.notify(notificationId, builder.build())
        } catch (e: SecurityException) {
            // Em caso de permissão de notificação revogada
        }
    }
}
