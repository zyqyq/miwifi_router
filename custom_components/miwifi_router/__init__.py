"""MiWiFi Router integration for Home Assistant.

Provides router statistics sensors and per-device tracking with speed data
via the Xiaomi MiWiFi router local API.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .api import MiWiFiAPIClient
from .const import (
    CONF_DEVICE_SCAN_INTERVAL,
    CONF_FORCE_HASH_ALGO,
    CONF_SPEED_UNIT,
    CONF_TOTAL_UNIT,
    CONF_UNIT_MODE,
    DEFAULT_DEVICE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_MODE,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MiWiFi Router from a config entry."""
    host = entry.data[CONF_HOST]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    device_scan_interval = entry.options.get(
        CONF_DEVICE_SCAN_INTERVAL, DEFAULT_DEVICE_SCAN_INTERVAL
    )
    force_hash_algo = entry.options.get(CONF_FORCE_HASH_ALGO) or None
    unit_mode = entry.options.get(CONF_UNIT_MODE, DEFAULT_UNIT_MODE) or DEFAULT_UNIT_MODE
    speed_unit = entry.options.get(CONF_SPEED_UNIT, SPEED_UNIT_AUTO) or SPEED_UNIT_AUTO
    total_unit = entry.options.get(CONF_TOTAL_UNIT, TOTAL_UNIT_AUTO) or TOTAL_UNIT_AUTO

    # Unit changes no longer need entity re-creation: the sensor native unit is
    # always the raw byte unit ("B/s" / "B") and Home Assistant converts it to
    # the suggested display unit, so history and statistics stay continuous.
    # Only the legacy bookkeeping options from the old behaviour are removed.
    _drop_legacy_unit_markers(hass, entry)

    # Create API client with hass instance for non-blocking aiohttp session
    api = MiWiFiAPIClient(host, password, hass=hass, force_hash_algo=force_hash_algo)

    # Create coordinator with layered polling and re-authorization support
    coordinator = MiWiFiCoordinator(
        hass=hass,
        api=api,
        scan_interval=scan_interval,
        device_scan_interval=device_scan_interval,
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
        "unit_mode: %s, speed_unit: %s, total_unit: %s)",
        host,
        scan_interval,
        device_scan_interval,
        unit_mode,
        speed_unit,
        total_unit,
    )

    return True


def _drop_legacy_unit_markers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove obsolete "_last_applied_*_unit" option keys from the entry.

    Older versions stored these markers to decide when to delete sensor
    entities after a unit change. Units no longer recreate entities, so the
    markers are meaningless and get dropped once.

    The options are only written back when such a key is actually present, so
    this cannot trigger a reload loop (the second setup finds nothing to drop),
    and it never raises.
    """
    stale_keys = [key for key in _LEGACY_UNIT_MARKER_KEYS if key in entry.options]
    if not stale_keys:
        return

    options = {
        key: value for key, value in entry.options.items() if key not in stale_keys
    }
    _LOGGER.debug(
        "MiWiFi Router: dropping obsolete option key(s): %s", ", ".join(stale_keys)
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
