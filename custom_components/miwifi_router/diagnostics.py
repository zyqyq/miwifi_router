"""Diagnostics support for the MiWiFi Router integration.

Exposes the configuration that matters for troubleshooting — polling cadence,
the adaptive polling state machine, router identity and a device count — while
making sure the router admin password is never exported.

Everything returned here must stay JSON-serialisable: Home Assistant writes it
verbatim into the diagnostics download.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACTIVE_SCAN_INTERVAL,
    CONF_ADAPTIVE_POLLING,
    CONF_DEVICE_SCAN_INTERVAL,
    CONF_FORCE_HASH_ALGO,
    CONF_IDLE_SCAN_INTERVAL,
    CONF_TRACKED_DEVICES,
    DEFAULT_ACTIVE_SCAN_INTERVAL,
    DEFAULT_ADAPTIVE_POLLING,
    DEFAULT_DEVICE_SCAN_INTERVAL,
    DEFAULT_IDLE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import MiWiFiCoordinator

# Never export the router admin password (or any future secret key) verbatim.
REDACTED = "**REDACTED**"
_SECRET_KEYS = (CONF_PASSWORD,)


def _redact(options: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``options`` with secret values masked."""
    redacted: dict[str, Any] = {}
    for key, value in (options or {}).items():
        if key in _SECRET_KEYS:
            redacted[key] = REDACTED if value else value
        else:
            redacted[key] = value
    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a MiWiFi Router config entry."""
    coordinator: MiWiFiCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )

    options = dict(entry.options or {})
    data = dict(entry.data or {})

    tracked = options.get(CONF_TRACKED_DEVICES) or {}
    tracked_count = len(tracked) if isinstance(tracked, (dict, list, set)) else 0

    diagnostics: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            # entry.data also holds the password — always redact it.
            "data": _redact(data),
            "options": _redact(options),
        },
        "intervals": {
            "scan_interval": options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            "device_scan_interval": options.get(
                CONF_DEVICE_SCAN_INTERVAL, DEFAULT_DEVICE_SCAN_INTERVAL
            ),
            "adaptive_polling": options.get(
                CONF_ADAPTIVE_POLLING, DEFAULT_ADAPTIVE_POLLING
            ),
            "idle_scan_interval": options.get(
                CONF_IDLE_SCAN_INTERVAL, DEFAULT_IDLE_SCAN_INTERVAL
            ),
            "active_scan_interval": options.get(
                CONF_ACTIVE_SCAN_INTERVAL, DEFAULT_ACTIVE_SCAN_INTERVAL
            ),
        },
        "tracked_devices": tracked_count,
        "tracked_device_macs": sorted(tracked) if isinstance(tracked, dict) else [],
        "coordinator_loaded": coordinator is not None,
    }

    if coordinator is None:
        # Integration not set up (yet) — still return the static configuration
        # instead of raising, so diagnostics never fail to download.
        diagnostics["adaptive"] = None
        diagnostics["router"] = None
        diagnostics["devices"] = {"merged_count": 0, "online_count": None}
        return diagnostics

    api = coordinator.api
    router_data = coordinator.router_data

    diagnostics["adaptive"] = coordinator.adaptive_status
    diagnostics["router"] = {
        "host": getattr(api, "_host", None) or data.get(CONF_HOST),
        "model": api.model,
        "firmware": api.firmware,
        "mac": api.mac,
        "force_hash_algo": options.get(CONF_FORCE_HASH_ALGO) or None,
    }
    diagnostics["devices"] = {
        "merged_count": len(router_data.devices),
        "online_count": router_data.status.get("count", {}).get("online"),
        "all_count": router_data.status.get("count", {}).get("all"),
    }
    diagnostics["coordinator"] = {
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval is not None
            else None
        ),
    }

    return diagnostics
