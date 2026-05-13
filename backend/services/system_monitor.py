"""
backend/services/system_monitor.py — RAM, CPU, VRAM stats
Uses psutil; VRAM via nvidia-smi subprocess
"""

import subprocess
import logging
import psutil

log = logging.getLogger("jarvis.sysmon")


class SystemMonitor:

    def get_stats(self) -> dict:
        ram   = psutil.virtual_memory()
        cpu   = psutil.cpu_percent(interval=None)

        stats = {
            "ram_used_gb":  round(ram.used  / 1e9, 1),
            "ram_total_gb": round(ram.total / 1e9, 1),
            "ram_percent":  ram.percent,
            "cpu_percent":  cpu,
            "vram_used_mb": None,
            "vram_total_mb": None,
        }

        # VRAM via nvidia-smi
        try:
            out = subprocess.check_output(
                ["nvidia-smi",
                 "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                timeout=3, stderr=subprocess.DEVNULL
            ).decode().strip()
            used, total = out.split(",")
            stats["vram_used_mb"]  = int(used.strip())
            stats["vram_total_mb"] = int(total.strip())
        except Exception:
            pass  # No NVIDIA GPU or nvidia-smi not in PATH

        return stats


# Singleton
system_monitor = SystemMonitor()
