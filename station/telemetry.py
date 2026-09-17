import platform
import importlib.metadata
import time
from pathlib import Path

import psutil


def collect(root: Path):
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(root))
    temperatures = {}
    try:
        for name, values in psutil.sensors_temperatures().items():
            temperatures[name] = [
                {"label": v.label, "celsius": v.current, "high": v.high} for v in values
            ]
    except (AttributeError, OSError):
        pass
    # Jetson and generic Linux thermal zones; absence remains explicitly unknown.
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            temperatures[zone.joinpath("type").read_text().strip()] = [
                {"celsius": int(zone.joinpath("temp").read_text()) / 1000}
            ]
        except (OSError, ValueError):
            continue
    rails = []
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        for f in hw.glob("*_input"):
            if not f.name.startswith(("in", "curr", "power", "fan")):
                continue
            try:
                prefix = f.stem.rsplit("_", 1)[0]
                label = hw / (prefix + "_label")
                rails.append(
                    {
                        "sensor": (
                            label.read_text().strip() if label.exists() else prefix
                        ),
                        "raw": int(f.read_text()),
                        "source": str(f),
                        "unit": (
                            "mV"
                            if prefix.startswith("in")
                            else (
                                "mA"
                                if prefix.startswith("curr")
                                else "µW" if prefix.startswith("power") else "RPM"
                            )
                        ),
                    }
                )
            except (OSError, ValueError):
                continue
    process = psutil.Process()
    versions = {}
    for name in (
        "torch",
        "torchvision",
        "timm",
        "opencv-python",
        "fastapi",
        "gpiod",
        "zxing-cpp",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    identity = {}
    for label, path in (
        ("board_model", "/proc/device-tree/model"),
        ("l4t_release", "/etc/nv_tegra_release"),
    ):
        try:
            identity[label] = Path(path).read_text().strip("\x00\n")
        except OSError:
            identity[label] = None
    gpu_load = []
    for path in Path("/sys/devices/platform").glob("*gpu/load"):
        try:
            gpu_load.append({"raw": path.read_text().strip(), "source": str(path)})
        except OSError:
            pass
    return {
        "observed_at": time.time(),
        "host": platform.node(),
        "os": platform.platform(),
        "versions": versions,
        "identity": identity,
        "gpu_load": gpu_load,
        "process_handles": (
            process.num_handles()
            if hasattr(process, "num_handles")
            else process.num_fds()
        ),
        "architecture": platform.machine(),
        "cpu_percent": psutil.cpu_percent(),
        "cpu_cores": psutil.cpu_count(),
        "memory_total": memory.total,
        "memory_available": memory.available,
        "memory_percent": memory.percent,
        "disk_total": disk.total,
        "disk_free": disk.free,
        "disk_percent": disk.percent,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "process_rss": process.memory_info().rss,
        "threads": process.num_threads(),
        "temperatures": temperatures,
        "hardware_sensors": rails,
        "external_supply_voltage": None,
        "belt_motion": None,
        "motor_current": None,
        "note": "None/빈 값은 미계측 또는 지원되지 않는 정보입니다. 출력 명령은 실제 회전을 증명하지 않습니다.",
    }
