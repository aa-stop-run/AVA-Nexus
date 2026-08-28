import time
import psutil


def obter_telemetria_sistema() -> dict:
    """Recolhe métricas de hardware da máquina / servidor."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
    except Exception:
        cpu_percent = 0.0

    try:
        mem = psutil.virtual_memory()
        ram_usada_gb = round(mem.used / (1024 ** 3), 1)
        ram_total_gb = round(mem.total / (1024 ** 3), 1)
        ram_percent = mem.percent
    except Exception:
        ram_usada_gb = 0.0
        ram_total_gb = 0.0
        ram_percent = 0.0

    try:
        disk = psutil.disk_usage("/")
        disk_usado_gb = round(disk.used / (1024 ** 3), 1)
        disk_total_gb = round(disk.total / (1024 ** 3), 1)
        disk_percent = disk.percent
    except Exception:
        try:
            disk = psutil.disk_usage("C:\\")
            disk_usado_gb = round(disk.used / (1024 ** 3), 1)
            disk_total_gb = round(disk.total / (1024 ** 3), 1)
            disk_percent = disk.percent
        except Exception:
            disk_usado_gb = 0.0
            disk_total_gb = 0.0
            disk_percent = 0.0

    try:
        boot_time = psutil.boot_time()
        uptime_segundos = int(time.time() - boot_time)
        dias = uptime_segundos // 86400
        horas = (uptime_segundos % 86400) // 3600
        uptime_texto = f"{dias}d {horas}h"
    except Exception:
        uptime_texto = "6h"

    return {
        "cpu_percent": cpu_percent,
        "ram_usada_gb": ram_usada_gb,
        "ram_total_gb": ram_total_gb,
        "ram_percent": ram_percent,
        "disk_usado_gb": disk_usado_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_percent,
        "uptime": uptime_texto,
    }
