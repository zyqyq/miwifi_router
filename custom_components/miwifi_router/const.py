"""Constants for the MiWiFi Router integration."""

DOMAIN = "miwifi_router"

# Config entry fields
CONF_HOST = "host"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEVICE_SCAN_INTERVAL = "device_scan_interval"
CONF_FORCE_HASH_ALGO = "force_hash_algo"  # Optional: "SHA1" | "SHA256" | None
CONF_SPEED_UNIT = "speed_unit"  # Optional: unit for speed sensors
CONF_TOTAL_UNIT = "total_unit"  # Optional: unit for total traffic sensors

# Speed unit options (for CONF_SPEED_UNIT)
# These are *display* unit choices now: the sensor native unit is always "B/s"
# and Home Assistant converts the raw byte value for the UI. "auto" = pick a
# readable unit automatically from the observed values.
SPEED_UNIT_AUTO = "auto"
SPEED_UNIT_OPTIONS: dict[str, str] = {
    "auto": "自动（在所选制式内按数值自动选择易读单位）",
    "B/s": "B/s（字节/秒）",
    "kB/s": "kB/s（千字节/秒，1000 进制）",
    "MB/s": "MB/s（兆字节/秒，1000 进制）",
    "GB/s": "GB/s（吉字节/秒，1000 进制）",
    "KiB/s": "KiB/s（千比字节/秒，1024 进制）",
    "MiB/s": "MiB/s（兆比字节/秒，1024 进制）",
    "GiB/s": "GiB/s（吉比字节/秒，1024 进制）",
    "bit/s": "bit/s（比特/秒）",
    "kbit/s": "kbit/s（千比特/秒）",
    "Mbit/s": "Mbit/s（兆比特/秒）",
    "Gbit/s": "Gbit/s（吉比特/秒）",
}

# Total unit options (for CONF_TOTAL_UNIT)
# Display unit choices; native unit stays "B". "auto" = pick one readable unit
# from the observed magnitude (totals keep that unit, they never switch).
TOTAL_UNIT_AUTO = "auto"
TOTAL_UNIT_OPTIONS: dict[str, str] = {
    "auto": "自动（在所选制式内按数值选一个稳定的易读单位）",
    "B": "B（字节）",
    "kB": "kB（千字节，1000 进制）",
    "MB": "MB（兆字节，1000 进制）",
    "GB": "GB（吉字节，1000 进制）",
    "TB": "TB（太字节，1000 进制）",
    "KiB": "KiB（千比字节，1024 进制）",
    "MiB": "MiB（兆比字节，1024 进制）",
    "GiB": "GiB（吉比字节，1024 进制）",
    "TiB": "TiB（太比字节，1024 进制）",
    "bit": "bit（比特）",
    "kbit": "kbit（千比特）",
    "Mbit": "Mbit（兆比特）",
    "Gbit": "Gbit（吉比特）",
}

# Unit conversion factors (number of bytes per unit)
# 1000进制 (SI) and 1024进制 (IEC) both supported.
# NOTE: units.py is the single source of truth for unit selection/conversion in
# the sensor platform; these dicts are kept populated (and in sync) so existing
# imports keep working.
SPEED_UNIT_FACTORS: dict[str, float] = {
    "B/s": 1.0,
    "kB/s": 1_000.0,
    "MB/s": 1_000_000.0,
    "GB/s": 1_000_000_000.0,
    "KiB/s": 1024.0,
    "MiB/s": 1024.0 * 1024.0,
    "GiB/s": 1024.0 * 1024.0 * 1024.0,
    "bit/s": 0.125,
    "kbit/s": 125.0,
    "Mbit/s": 125_000.0,
    "Gbit/s": 125_000_000.0,
}

TOTAL_UNIT_FACTORS: dict[str, float] = {
    "B": 1.0,
    "kB": 1_000.0,
    "MB": 1_000_000.0,
    "GB": 1_000_000_000.0,
    "TB": 1_000_000_000_000.0,
    "KiB": 1024.0,
    "MiB": 1024.0 * 1024.0,
    "GiB": 1024.0 * 1024.0 * 1024.0,
    "TiB": 1024.0 * 1024.0 * 1024.0 * 1024.0,
    "bit": 0.125,
    "kbit": 125.0,
    "Mbit": 125_000.0,
    "Gbit": 125_000_000.0,
}

# ---------------------------------------------------------------------------
# Unit family: bit vs byte display (v1.7.0+, split per sensor group in v1.8.0)
# ---------------------------------------------------------------------------
# The native unit of the byte-based sensors is ALWAYS raw bytes ("B/s" for
# speeds, "B" for totals) so long-term statistics stay continuous. The unit
# family only selects the display family that Home Assistant converts to, and
# speeds and totals are configured independently.
CONF_SPEED_UNIT_MODE = "speed_unit_mode"   # 实时网速显示单位制式：byte / bit
CONF_TOTAL_UNIT_MODE = "total_unit_mode"   # 累计流量显示单位制式：byte / bit
UNIT_MODE_BYTE = "byte"
UNIT_MODE_BIT = "bit"
DEFAULT_SPEED_UNIT_MODE = UNIT_MODE_BYTE
DEFAULT_TOTAL_UNIT_MODE = UNIT_MODE_BYTE

# Legacy key used by v1.7.0 (a single family for both groups). It is read once
# and migrated into the two keys above, then removed from the entry options.
CONF_UNIT_MODE = "unit_mode"
DEFAULT_UNIT_MODE = DEFAULT_SPEED_UNIT_MODE

UNIT_MODE_OPTIONS: dict[str, str] = {
    "byte": "字节（B/s、kB/s、MB/s / B、kB、MB、GB…）",
    "bit": "比特（bit/s、kbit/s、Mbit/s / bit、kbit、Mbit、Gbit…）",
}

# Default values
DEFAULT_SCAN_INTERVAL = 10  # seconds - for realtime data (speeds, counts)
DEFAULT_DEVICE_SCAN_INTERVAL = 30  # seconds - for device list details

# Per-device sensor configuration
CONF_TRACKED_DEVICES = "tracked_devices"  # dict: {mac: device_name}

# Router API endpoints
# Login endpoint - does NOT use stok, accessed directly
API_LOGIN = "/cgi-bin/luci/api/xqsystem/login"

# Logout endpoint - uses stok to end the session
API_LOGOUT = "/web/logout"

# Authenticated endpoints - accessed via /cgi-bin/luci/;stok=XXX{endpoint}
# These paths are based on diagnostic results from BE5000 (RD18) firmware 1.0.53
API_STATUS = "/api/misystem/status"              # Device speeds + WAN stats
API_DEVICE_LIST = "/api/xqsystem/device_list"    # Detailed device list
API_INIT_INFO = "/api/xqsystem/init_info"        # Router hardware/firmware info
API_NEWSTATUS = "/api/misystem/newstatus"        # Extended status with hardware info
API_WIFI_DETAIL = "/api/xqnetwork/wifi_detail_all"  # WiFi band details
API_SYSTEM_STATUS = "/api/xqsystem/status"       # System status with WAN statistics
API_REBOOT = "/api/xqsystem/reboot"               # Reboot router

# Login algorithm constants
PUBLIC_KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"

# Device tracker attributes
DEVICE_ATTR_MAC = "mac"
DEVICE_ATTR_NAME = "devname"
DEVICE_ATTR_ONLINE = "online"
DEVICE_ATTR_UPSPEED = "upspeed"
DEVICE_ATTR_DOWNSPEED = "downspeed"
DEVICE_ATTR_UPLOAD = "upload"
DEVICE_ATTR_DOWNLOAD = "download"
DEVICE_ATTR_MAX_UPSPEED = "maxuploadspeed"
DEVICE_ATTR_MAX_DOWNSPEED = "maxdownloadspeed"
DEVICE_ATTR_ISAP = "isap"
DEVICE_ATTR_IP = "ip"
DEVICE_ATTR_AUTHED = "authority"

# Sensor types for router stats
SENSOR_TYPES = {
    "download_speed": {
        "name": "Download Speed",
        "native_unit_of_measurement": "B/s",
        "icon": "mdi:download",
        "device_class": None,
        "state_class": "measurement",
    },
    "upload_speed": {
        "name": "Upload Speed",
        "native_unit_of_measurement": "B/s",
        "icon": "mdi:upload",
        "device_class": None,
        "state_class": "measurement",
    },
    "download_total": {
        "name": "Download Total",
        "native_unit_of_measurement": "B",
        "icon": "mdi:download-circle",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "upload_total": {
        "name": "Upload Total",
        "native_unit_of_measurement": "B",
        "icon": "mdi:upload-circle",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "online_devices": {
        "name": "Online Devices",
        "native_unit_of_measurement": "devices",
        "icon": "mdi:devices",
        "device_class": None,
        "state_class": "measurement",
    },
    "cpu_load": {
        "name": "CPU Load",
        "native_unit_of_measurement": "%",
        "icon": "mdi:cpu-64-bit",
        "device_class": None,
        "state_class": "measurement",
    },
    "memory_usage": {
        "name": "Memory Usage",
        "native_unit_of_measurement": "%",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": "measurement",
    },
    "temperature": {
        "name": "Temperature",
        "native_unit_of_measurement": "°C",
        "icon": "mdi:thermometer",
        "device_class": "temperature",
        "state_class": "measurement",
    },
}

# ---------------------------------------------------------------------------
# Adaptive polling (implemented in adaptive.py)
# ---------------------------------------------------------------------------
# 自适应轮询：根据 WAN 流量与设备变化动态调整实时数据轮询间隔，
# 空闲时拉长间隔降低路由器负载，流量突增/设备上下线时临时缩短间隔。
# Adaptive polling: dynamically adjusts the tier-1 interval; long when the
# network is quiet, short around traffic bursts and device churn.

# Option keys (config flow / options flow)
CONF_ADAPTIVE_POLLING = "adaptive_polling"          # 是否启用自适应轮询
CONF_IDLE_SCAN_INTERVAL = "idle_scan_interval"      # 空闲模式轮询间隔（秒）
CONF_ACTIVE_SCAN_INTERVAL = "active_scan_interval"  # 流量突增模式轮询间隔（秒）
CONF_IDLE_TRAFFIC_KBPS = "idle_traffic_kbps"        # 空闲判定阈值（KB/s）
CONF_ACTIVE_TRAFFIC_KBPS = "active_traffic_kbps"    # 进入活跃模式阈值（KB/s）

# Defaults
DEFAULT_ADAPTIVE_POLLING = True
DEFAULT_IDLE_SCAN_INTERVAL = 60
DEFAULT_ACTIVE_SCAN_INTERVAL = 5
DEFAULT_IDLE_TRAFFIC_KBPS = 1.0     # 速率 ≤ 1 KB/s 视为空闲采样
DEFAULT_ACTIVE_TRAFFIC_KBPS = 32.0  # 速率 ≥ 32 KB/s 视为流量突增（立即 active）

# 轮询间隔与阈值的可填范围：UI 直接校验，而不是静默夹取
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 3600
KBPS_TO_BPS = 1000.0

# Hard limits and thresholds used by AdaptiveConfig
ADAPTIVE_MIN_INTERVAL = 5                  # 任何模式下的最小轮询间隔（秒）
ADAPTIVE_MAX_INTERVAL = 300                # 任何模式下的最大轮询间隔（秒）
ADAPTIVE_IDLE_TRAFFIC_BPS = 1024           # ≤ 该值视为空闲采样（字节/秒）
ADAPTIVE_ACTIVE_TRAFFIC_BPS = 32768        # ≥ 该值视为流量突增（字节/秒）
ADAPTIVE_IDLE_SAMPLES = 6                  # 连续空闲采样次数后才进入空闲模式
ADAPTIVE_ACTIVE_HOLD_SECONDS = 60          # 最后一次事件后保持活跃的秒数
ADAPTIVE_MIN_DWELL_SECONDS = 15            # 模式降级前的最短驻留时间（秒）
ADAPTIVE_DEVICE_STABLE_SECONDS = 300       # 设备集合需稳定的秒数才允许空闲

