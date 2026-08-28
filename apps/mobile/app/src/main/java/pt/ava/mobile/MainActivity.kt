package pt.ava.mobile

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var offlineView: LinearLayout
    private lateinit var btnRetry: Button
    private lateinit var btnConfig: Button

    private lateinit var healthManager: HealthConnectManager

    // Launcher para permissões do Health Connect
    private val healthPermissionLauncher = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) { grantedPermissions ->
        if (grantedPermissions.containsAll(healthManager.requiredPermissions)) {
            Toast.makeText(this, "Health Connect autorizado com sucesso!", Toast.LENGTH_SHORT).show()
            agendarSincronizacao()
        } else {
            Toast.makeText(this, "Algumas permissões de saúde não foram concedidas.", Toast.LENGTH_LONG).show()
        }
    }

    // Launcher para gravação de áudio nativa
    private val recordAudioLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            Toast.makeText(this, "Microfone autorizado para comandos da AVA.", Toast.LENGTH_SHORT).show()
        }
    }

    // Launcher para notificações no Android 13+
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            Toast.makeText(this, "Notificações e alarmes da AVA autorizados.", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Configurar Safe Area / Insets para que a barra de estado e os botões não sobreponham a app
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.parseColor("#07090E")
        window.navigationBarColor = Color.parseColor("#07090E")
        val insetsController = WindowCompat.getInsetsController(window, window.decorView)
        insetsController.isAppearanceLightStatusBars = false
        insetsController.isAppearanceLightNavigationBars = false

        val rootLayout = findViewById<View>(R.id.rootLayout)
        ViewCompat.setOnApplyWindowInsetsListener(rootLayout) { view, windowInsets ->
            val insets = windowInsets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
            )
            view.setPadding(insets.left, insets.top, insets.right, insets.bottom)
            windowInsets
        }

        webView = findViewById(R.id.webView)
        progressBar = findViewById(R.id.progressBar)
        offlineView = findViewById(R.id.offlineView)
        btnRetry = findViewById(R.id.btnRetry)
        btnConfig = findViewById(R.id.btnConfig)

        healthManager = HealthConnectManager(this)

        // Criar Canais de Notificação de Alta Prioridade
        NotificationHelper.createNotificationChannels(this)

        configurarWebView()
        verificarPermissoesAudio()
        verificarPermissoesNotificacoes()
        verificarPermissoesSaude()
        agendarSincronizacao()

        btnRetry.setOnClickListener {
            carregarHub()
        }

        btnConfig.setOnClickListener {
            mostrarDialogoConfiguracao()
        }

        carregarHub()
    }

    private fun configurarWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowFileAccess = true

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progressBar.visibility = View.VISIBLE
                offlineView.visibility = View.GONE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progressBar.visibility = View.GONE
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    progressBar.visibility = View.GONE
                    webView.visibility = View.GONE
                    offlineView.visibility = View.VISIBLE
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
                if (newProgress >= 100) {
                    progressBar.visibility = View.GONE
                }
            }

            override fun onPermissionRequest(request: PermissionRequest?) {
                if (request == null) return
                val requestedResources = request.resources
                for (resource in requestedResources) {
                    if (resource == PermissionRequest.RESOURCE_AUDIO_CAPTURE) {
                        request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                        return
                    }
                }
                request.deny()
            }
        }
    }

    private fun carregarHub() {
        val url = Config.getHubUrl(this)
        offlineView.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(url)
    }

    private fun verificarPermissoesAudio() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            recordAudioLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun verificarPermissoesNotificacoes() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun verificarPermissoesSaude() {
        lifecycleScope.launch {
            if (healthManager.healthConnectClient != null) {
                if (!healthManager.hasAllPermissions()) {
                    healthPermissionLauncher.launch(healthManager.requiredPermissions)
                }
            }
        }
    }

    private fun agendarSincronizacao() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        // 1. Sincronização periódica de Saúde (Galaxy Watch) a cada 1 hora
        val periodicHealthRequest = PeriodicWorkRequestBuilder<HealthSyncWorker>(1, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            HealthSyncWorker.WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            periodicHealthRequest
        )
        WorkManager.getInstance(this).enqueue(
            OneTimeWorkRequestBuilder<HealthSyncWorker>().setConstraints(constraints).build()
        )

        // 2. Sincronização periódica da Agenda de Medicação a cada 6 horas
        val periodicMedRequest = PeriodicWorkRequestBuilder<MedicationSyncWorker>(6, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "ava_medication_sync_periodic",
            ExistingPeriodicWorkPolicy.KEEP,
            periodicMedRequest
        )
        WorkManager.getInstance(this).enqueue(
            OneTimeWorkRequestBuilder<MedicationSyncWorker>().setConstraints(constraints).build()
        )

        // 3. Notificações Proativas de Radar a cada 3 horas
        val periodicRadarRequest = PeriodicWorkRequestBuilder<RadarNotificationWorker>(3, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "ava_radar_notification_periodic",
            ExistingPeriodicWorkPolicy.KEEP,
            periodicRadarRequest
        )
    }

    private fun mostrarDialogoConfiguracao() {
        val input = EditText(this).apply {
            setText(Config.getHubUrl(this@MainActivity))
            hint = "http://localhost:8088"
        }

        AlertDialog.Builder(this)
            .setTitle("Configurar Servidor AVA")
            .setMessage("Introduz o endereço Tailscale ou IP local do teu servidor AVA:")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                val novaUrl = input.text.toString().trim()
                if (novaUrl.isNotEmpty()) {
                    Config.setHubUrl(this, novaUrl)
                    carregarHub()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
