package pt.ava.mobile

import android.content.Context
import android.content.SharedPreferences

object Config {
    private const val PREFS_NAME = "ava_mobile_prefs"
    private const val KEY_HUB_URL = "hub_url"
    private const val KEY_DEVICE_TOKEN = "device_token"
    private const val KEY_TITULAR = "titular"

    // IP Tailscale do servidor AVA (Linux ava) na porta do Hub (8088)
    private const val DEFAULT_HUB_URL = "http://localhost:8088"
    private const val DEFAULT_TOKEN = "ava-mobile-device-token-2026"
    private const val DEFAULT_TITULAR = "aa-stop-run"

    private fun getPrefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    fun getHubUrl(context: Context): String {
        return getPrefs(context).getString(KEY_HUB_URL, DEFAULT_HUB_URL) ?: DEFAULT_HUB_URL
    }

    fun setHubUrl(context: Context, url: String) {
        val normalized = if (!url.startsWith("http://") && !url.startsWith("https://")) {
            "http://$url"
        } else {
            url
        }.trimEnd('/')
        getPrefs(context).edit().putString(KEY_HUB_URL, normalized).apply()
    }

    fun getDeviceToken(context: Context): String {
        return getPrefs(context).getString(KEY_DEVICE_TOKEN, DEFAULT_TOKEN) ?: DEFAULT_TOKEN
    }

    fun getTitular(context: Context): String {
        return getPrefs(context).getString(KEY_TITULAR, DEFAULT_TITULAR) ?: DEFAULT_TITULAR
    }
}
