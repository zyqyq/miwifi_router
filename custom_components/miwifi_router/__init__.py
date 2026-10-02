"""MiWiFi Router integration for Home Assistant.

Provides router statistics sensors and per-device tracking with speed data
via the Xiaomi MiWiFi router local API.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .api import MiWiFiAPIClient
from .const import (
    CONF_ACTIVE_SCAN_INTERVAL,
    CONF_ACTIVE_TRAFFIC_KBPS,
    CONF_ADAPTIVE_POLLING,
    CONF_DEVICE_SCAN_INTERVAL,
    CONF_FORCE_HASH_ALGO,
    CONF_IDLE_SCAN_INTERVAL,
    CONF_IDLE_TRAFFIC_KBPS,
    CONF_SPEED_UNIT,
    CONF_SPEED_UNIT_MODE,
    CONF_TOTAL_UNIT,
    CONF_TOTAL_UNIT_MODE,
    CONF_UNIT_MODE,
    DEFAULT_ACTIVE_SCAN_INTERVAL,
    DEFAULT_ACTIVE_TRAFFIC_KBPS,
    DEFAULT_ADAPTIVE_POLLING,
    DEFAULT_DEVICE_SCAN_INTERVAL,
    DEFAULT_IDLE_SCAN_INTERVAL,
    DEFAULT_IDLE_TRAFFIC_KBPS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPEED_UNIT_MODE,
    DEFAULT_TOTAL_UNIT_MODE,
    DOMAIN,
    SPEED_UNIT_AUTO,
    TOTAL_UNIT_AUTO,
)
from .coordinator import MiWiFiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.BUTTON]

# Obsolete option keys written by older versions that deleted sensor entities
# when the units changed. They are dropped from the entry options on setup.
_LEGACY_UNIT_MARKER_KEYS = ("_last_applied_speed_unit", "_last_applied_total_unit")


def _unit_modes(options: Mapping[str, Any]) -> tuple[str, str]:
    """Return the (speed, total) display unit family from the entry options.

    v1.7.0 only had a single shared ``unit_mode`` key; it is still honoured for
    both groups so an existing entry keeps its setting until the options are
    saved again (``_migrate_legacy_options`` also copies it over explicitly).
    """
    legacy = options.get(CONF_UNIT_MODE)
    speed = options.get(CONF_SPEED_UNIT_MODE) or legacy or DEFAULT_SPEED_UNIT_MODE
    total = options.get(CONF_TOTAL_UNIT_MODE) or legacy or DEFAULT_TOTAL_UNIT_MODE
    return str(speed), str(total)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MiWiFi Router from a config entry."""
    host = entry.data[CONF_HOST]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    device_scan_interval = entry.options.get(
        CONF_DEVICE_SCAN_INTERVAL, DEFAULT_DEVICE_SCAN_INTERVAL
    )
    adaptive_polling = entry.options.get(
        CONF_ADAPTIVE_POLLING, DEFAULT_ADAPTIVE_POLLING
    )
    idle_scan_interval = entry.options.get(
        CONF_IDLE_SCAN_INTERVAL, DEFAULT_IDLE_SCAN_INTERVAL
    )
    active_scan_interval = entry.options.get(
        CONF_ACTIVE_SCAN_INTERVAL, DEFAULT_ACTIVE_SCAN_INTERVAL
    )
    idle_traffic_kbps = entry.options.get(
        CONF_IDLE_TRAFFIC_KBPS, DEFAULT_IDLE_TRAFFIC_KBPS
    )
    active_traffic_kbps = entry.options.get(
        CONF_ACTIVE_TRAFFIC_KBPS, DEFAULT_ACTIVE_TRAFFIC_KBPS
    )
    force_hash_algo = entry.options.get(CONF_FORCE_HASH_ALGO) or None
    speed_unit = entry.options.get(CONF_SPEED_UNIT, SPEED_UNIT_AUTO) or SPEED_UNIT_AUTO
    total_unit = entry.options.get(CONF_TOTAL_UNIT, TOTAL_UNIT_AUTO) or TOTAL_UNIT_AUTO
    speed_unit_mode, total_unit_mode = _unit_modes(entry.options)

    # Unit changes no longer need entity re-creation: the sensor native unit is
    # always the raw byte unit ("B/s" / "B") and Home Assistant converts it to
    # the suggested display unit, so history and statistics stay continuous.
    # Only the legacy bookkeeping options from the old behaviour are removed.
    _migrate_legacy_options(hass, entry)

    # Create API client with hass instance for non-blocking aiohttp session
    api = MiWiFiAPIClient(host, password, hass=hass, force_hash_algo=force_hash_algo)

    # Create coordinator with layered polling and re-authorization support
    coordinator = MiWiFiCoordinator(
        hass=hass,
        api=api,
        scan_interval=scan_interval,
        device_scan_interval=device_scan_interval,
        adaptive_polling=adaptive_polling,
        idle_scan_interval=idle_scan_interval,
        active_scan_interval=active_scan_interval,
        idle_traffic_kbps=idle_traffic_kbps,
        active_traffic_kbps=active_traffic_kbps,
    )

    # Store in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Perform first data fetch (includes retry with backoff on failure)
    await coordinator.async_config_entry_first_refresh()

    # Set up platforms (sensors + device trackers)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "MiWiFi Router integration set up for %s (scan: %ds, device: %ds, "
        "adaptive_polling: %s, idle: %ds, active: %ds, "
        "idle_threshold: %s KB/s, active_threshold: %s KB/s, "
        "speed_unit_mode: %s, total_unit_mode: %s, "
        "speed_unit: %s, total_unit: %s)",
        host,
        scan_interval,
        device_scan_interval,
        adaptive_polling,
        idle_scan_interval,
        active_scan_interval,
        idle_traffic_kbps,
        active_traffic_kbps,
        speed_unit_mode,
        total_unit_mode,
        speed_unit,
        total_unit,
    )

    return True


def _migrate_legacy_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up obsolete option keys and split the legacy shared unit mode.

    Two kinds of legacy keys exist:

    * ``_last_applied_speed_unit`` / ``_last_applied_total_unit`` — bookkeeping
      of the old "delete the entities when the unit changes" behaviour.
    * ``unit_mode`` — the v1.7.0 single display-unit family shared by speeds and
      totals. It is copied into ``speed_unit_mode`` / ``total_unit_mode`` (when
      those are not set yet) and then removed, so the user keeps the setting.

    The options are only written back when something actually changed, so this
    cannot trigger a reload loop, and it never raises.
    """
    options = dict(entry.options)
    changed = False

    legacy_mode = options.get(CONF_UNIT_MODE)
    if legacy_mode:
        for key, default in (
            (CONF_SPEED_UNIT_MODE, DEFAULT_SPEED_UNIT_MODE),
            (CONF_TOTAL_UNIT_MODE, DEFAULT_TOTAL_UNIT_MODE),
        ):
            if not options.get(key):
                options[key] = legacy_mode or default
        del options[CONF_UNIT_MODE]
        changed = True

    for key in _LEGACY_UNIT_MARKER_KEYS:
        if key in options:
            del options[key]
            changed = True

    if not changed:
        return

    _LOGGER.debug(
        "MiWiFi Router: migrating legacy option keys (speed_unit_mode=%s, "
        "total_unit_mode=%s)",
        options.get(CONF_SPEED_UNIT_MODE),
        options.get(CONF_TOTAL_UNIT_MODE),
    )
    hass.config_entries.async_update_entry(entry, options=options)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a MiWiFi Router config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: MiWiFiCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.api.close()

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update - reload the integration."""
    await hass.config_entries.async_reload(entry.entry_id)
