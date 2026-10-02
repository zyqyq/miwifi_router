"""Sensor platform for MiWiFi Router.

Provides sensors for:
- Download/Upload speed (raw bytes; display unit configurable)
- Download/Upload total (raw bytes; display unit configurable)
- Online device count
- CPU load (%)
- Memory usage (%)
- Speed TOP5 (unitless raw bytes/s, see below)
- Per-device speed/traffic sensors (configurable via Options)

Unit architecture (v1.7.0+)
---------------------------
* ``native_unit_of_measurement`` is ALWAYS the raw byte unit
  (``B/s`` for speeds, ``B`` for total traffic) and ``native_value`` is ALWAYS
  the raw, unconverted byte value. Long-term statistics therefore keep raw byte
  continuity and the entity identity (``unique_id``) never changes.
* ``device_class`` (``DATA_RATE`` / ``DATA_SIZE``) lets Home Assistant perform
  the native -> display conversion itself, in the UI.
* The display unit is expressed with
  ``SensorEntityDescription.suggested_unit_of_measurement``, resolved from the
  options: the unit family (``unit_mode`` = ``byte`` / ``bit``) plus either an
  explicit unit or ``"auto"`` (readable auto-scaling, see ``units.py``).
  Users can additionally override the display unit per entity in the UI.
* Changing the unit options does NOT recreate entities and does NOT lose
  history: the options-update listener simply reloads the config entry, the
  platform re-creates the entities with the SAME ``unique_id`` and Home
  Assistant keeps showing the same statistics in the new display unit.
* Attributes keep ``raw_b`` (raw byte value, int) for backwards compatibility
  and ``human_readable`` (auto-scaled string honouring the bit/byte family),
  plus ``display_unit`` with the unit currently suggested to Home Assistant.
* Only if ``suggested_unit_of_measurement`` is unavailable (very old Home
  Assistant cores) do we fall back to the legacy behaviour: the resolved
  display unit is baked into ``native_unit_of_measurement`` and the value is
  converted before it is reported. Auto-scaling is disabled in that fallback.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import translation
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import units
from .const import (
    CONF_SPEED_UNIT,
    CONF_TOTAL_UNIT,
    CONF_TRACKED_DEVICES,
    CONF_UNIT_MODE,
    DEFAULT_UNIT_MODE,
    DOMAIN,
    SPEED_UNIT_AUTO,
    TOTAL_UNIT_AUTO,
)
from .coordinator import MiWiFiCoordinator

_LOGGER = logging.getLogger(__name__)

# Fixed raw-byte native units. These literals must stay exactly "B/s" and "B":
# the recorder already stores statistics with unit "B/s"/unit_class "data_rate"
# and "B"/unit_class "information", and any change would break their continuity.
NATIVE_RATE_UNIT = UnitOfDataRate.BYTES_PER_SECOND  # "B/s"
NATIVE_SIZE_UNIT = UnitOfInformation.BYTES  # "B"

# ``suggested_unit_of_measurement`` was added to SensorEntityDescription in a
# later Home Assistant release. Guard for compatibility so the integration
# still loads (with raw byte units) on older cores.
_HAS_SUGGESTED_UNIT = "suggested_unit_of_measurement" in getattr(
    SensorEntityDescription, "__dataclass_fields__", {}
)

# Map of top-level byte-based sensors to their /api/misystem/status WAN field.
_UNIT_SENSOR_FIELDS: dict[str, str] = {
    "download_speed": "downspeed",
    "upload_speed": "upspeed",
    "download_total": "download",
    "upload_total": "upload",
}

# Map of per-device byte-based sensors to their device dict field.
_DEVICE_UNIT_FIELDS: dict[str, str] = {
    "device_download_speed": "downspeed",
    "device_upload_speed": "upspeed",
    "device_download_total": "download",
    "device_upload_total": "upload",
}


def _format_speed(speed_bytes: float) -> str:
    """Format speed value for display in attributes (byte family)."""
    return units.human_readable_rate(speed_bytes, units.UNIT_MODE_BYTE)


def _format_bytes(total_bytes: float) -> str:
    """Format total bytes for display in attributes (byte family)."""
    return units.human_readable_size(total_bytes, units.UNIT_MODE_BYTE)


def _human_readable(raw_bytes: float, is_speed: bool, mode: str) -> str:
    """Format a raw byte value honouring the configured unit family."""
    if is_speed:
        return units.human_readable_rate(raw_bytes, mode)
    return units.human_readable_size(raw_bytes, mode)


def _convert_value(raw_bytes: float, unit: str) -> float:
    """Convert raw byte value to the target unit (delegates to units.py).

    Kept for backwards compatibility with older callers/imports.
    """
    return units.convert_from_bytes(raw_bytes, unit)


def _as_number(value: Any) -> float | int:
    """Coerce an arbitrary value to a finite number (int when integral)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return int(number) if number.is_integer() else number


def _as_int(value: Any) -> int:
    """Coerce an arbitrary value to an int byte count; never raises."""
    return int(_as_number(value))


def _round_value(value: float) -> float:
    """Round converted value to reasonable precision.

    For very small values, keep more decimals; for large values, fewer.
    """
    if value == 0:
        return 0
    abs_val = abs(value)
    if abs_val < 0.01:
        return round(value, 6)
    if abs_val < 1:
        return round(value, 4)
    if abs_val < 100:
        return round(value, 3)
    if abs_val < 10_000:
        return round(value, 2)
    return round(value, 1)


class _UnitResolver:
    """Resolve native/display units for a single byte-based sensor entity.

    Native values always stay raw bytes. The resolver only decides which
    *display* unit should be suggested to Home Assistant, and (only on cores
    without ``suggested_unit_of_measurement``) whether the reported value has to
    be pre-converted to an explicit legacy unit.
    """

    def __init__(
        self,
        *,
        is_speed: bool,
        mode: str,
        choice: str,
        legacy: bool = False,
    ) -> None:
        """Initialize the resolver for one entity."""
        self.is_speed = is_speed
        self.mode = (
            mode
            if mode in (units.UNIT_MODE_BYTE, units.UNIT_MODE_BIT)
            else units.UNIT_MODE_BYTE
        )
        self.legacy = legacy
        # An explicit unit that does not belong to the selected family (e.g.
        # "MB/s" while unit_mode == "bit") resolves to None -> auto-scaling.
        self._explicit = units.resolve_unit(self.mode, choice, is_speed)
        self._scaler: units.AutoUnitScaler | None = None
        self._fixed_auto: str | None = None
        # Totals keep one stable unit; it is picked once from the first
        # non-zero sample (never re-picked, they feed TOTAL_INCREASING stats).
        self._auto_locked = False
        if not legacy and self._explicit is None:
            if is_speed:
                self._scaler = units.AutoUnitScaler(is_speed=True, mode=self.mode)
            else:
                # Start from the family's base unit ("B" / "bit") until the
                # first non-zero magnitude is observed.
                self._fixed_auto = units.base_unit(False, self.mode)

    @property
    def native_unit(self) -> str:
        """Return the unit of the reported value (raw bytes unless legacy)."""
        if self.legacy and self._explicit:
            return self._explicit
        return NATIVE_RATE_UNIT if self.is_speed else NATIVE_SIZE_UNIT

    @property
    def explicit_unit(self) -> str | None:
        """Return the explicitly configured display unit, if any."""
        return self._explicit

    @property
    def display_unit(self) -> str | None:
        """Return the suggested display unit (None = show the native unit)."""
        if self._explicit is not None:
            return self._explicit
        if self.legacy:
            return None
        if self._scaler is not None:
            return self._scaler.unit
        return self._fixed_auto

    def process(self, raw_value: Any) -> tuple[float | int, str | None]:
        """Observe a raw byte sample and return (value, display unit).

        The returned value is the raw byte value (native unit) except in the
        legacy fallback, where the value is pre-converted to the explicit unit.
        """
        raw = _as_number(raw_value)
        if self.legacy:
            if self._explicit:
                converted = units.convert_from_bytes(raw, self._explicit)
                return _round_value(converted), self._explicit
            return raw, None
        if self._explicit is not None:
            return raw, self._explicit
        if self._scaler is not None:
            return raw, self._scaler.observe(raw)
        # Totals: pick one stable unit from the first non-zero magnitude and
        # keep it. Totals feed TOTAL_INCREASING statistics and must not switch
        # their display unit dynamically.
        if not self._auto_locked and raw > 0:
            self._fixed_auto = units.auto_size_unit(raw, self.mode)
            self._auto_locked = True
        return raw, self._fixed_auto

    def display_pair(self, raw_value: Any) -> tuple[float, str]:
        """Return (converted value, display unit) without touching entity state.

        Used for attributes that expose a second, readable representation of a
        raw byte value (e.g. the unitless speed TOP5 sensor).
        """
        raw = _as_number(raw_value)
        unit = self._explicit or units.pick_readable_unit(
            raw, self.mode, is_speed=self.is_speed
        )
        return _round_value(units.convert_from_bytes(raw, unit)), unit


def _build_unit_description(
    *,
    key: str,
    translation_key: str,
    is_speed: bool,
    icon: str,
    state_class: SensorStateClass | None,
    mode: str,
    choice: str,
) -> tuple[SensorEntityDescription, _UnitResolver]:
    """Build a SensorEntityDescription for a byte-based sensor.

    ``native_unit_of_measurement`` is always the raw byte unit; the user-facing
    display unit is passed as ``suggested_unit_of_measurement`` (or baked into
    the native unit on cores that do not support suggestions).
    """
    resolver = _UnitResolver(
        is_speed=is_speed, mode=mode, choice=choice, legacy=not _HAS_SUGGESTED_UNIT
    )
    kwargs: dict[str, Any] = {
        "key": key,
        "translation_key": translation_key,
        "icon": icon,
        "state_class": state_class,
        "device_class": (
            SensorDeviceClass.DATA_RATE if is_speed else SensorDeviceClass.DATA_SIZE
        ),
        "native_unit_of_measurement": resolver.native_unit,
    }
    if _HAS_SUGGESTED_UNIT and resolver.display_unit:
        kwargs["suggested_unit_of_measurement"] = resolver.display_unit
    return SensorEntityDescription(**kwargs), resolver


# Per-device sensor description templates
# Tuple: (key, translation_key, is_speed, icon, state_class)
# - translation_key: used by HA to look up translated name from translations/<lang>.json
# - is_speed: True for speed sensors (use CONF_SPEED_UNIT), False for total (use CONF_TOTAL_UNIT)
# - native_unit is always raw bytes (B/s or B); the display unit comes from
#   suggested_unit_of_measurement and device_class handles the conversion.
DEVICE_SENSOR_KEYS: list[tuple[str, str, bool, str, SensorStateClass | None]] = [
    (
        "device_download_speed",
        "download_speed",
        True,
        "mdi:download",
        SensorStateClass.MEASUREMENT,
    ),
    (
        "device_upload_speed",
        "upload_speed",
        True,
        "mdi:upload",
        SensorStateClass.MEASUREMENT,
    ),
    (
        "device_download_total",
        "download_total",
        False,
        "mdi:download-circle",
        SensorStateClass.TOTAL_INCREASING,
    ),
    (
        "device_upload_total",
        "upload_total",
        False,
        "mdi:upload-circle",
        SensorStateClass.TOTAL_INCREASING,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MiWiFi Router sensors from a config entry."""
    coordinator: MiWiFiCoordinator = hass.data[DOMAIN][entry.entry_id]
    api = coordinator.api

    # Read user-selected unit mode and display units from options.
    # "auto" means auto-scaling; explicit units are only accepted when they
    # belong to the selected family (see units.resolve_unit).
    unit_mode = entry.options.get(CONF_UNIT_MODE, DEFAULT_UNIT_MODE) or DEFAULT_UNIT_MODE
    speed_unit_cfg = entry.options.get(CONF_SPEED_UNIT, SPEED_UNIT_AUTO) or SPEED_UNIT_AUTO
    total_unit_cfg = entry.options.get(CONF_TOTAL_UNIT, TOTAL_UNIT_AUTO) or TOTAL_UNIT_AUTO

    entities: list[MiWiFiRouterSensor] = []

    entity_specs: list[tuple[SensorEntityDescription, _UnitResolver | None]] = [
        _build_unit_description(
            key="download_speed",
            translation_key="download_speed",
            is_speed=True,
            icon="mdi:download",
            state_class=SensorStateClass.MEASUREMENT,
            mode=unit_mode,
            choice=speed_unit_cfg,
        ),
        _build_unit_description(
            key="upload_speed",
            translation_key="upload_speed",
            is_speed=True,
            icon="mdi:upload",
            state_class=SensorStateClass.MEASUREMENT,
            mode=unit_mode,
            choice=speed_unit_cfg,
        ),
        _build_unit_description(
            key="download_total",
            translation_key="download_total",
            is_speed=False,
            icon="mdi:download-circle",
            state_class=SensorStateClass.TOTAL_INCREASING,
            mode=unit_mode,
            choice=total_unit_cfg,
        ),
        _build_unit_description(
            key="upload_total",
            translation_key="upload_total",
            is_speed=False,
            icon="mdi:upload-circle",
            state_class=SensorStateClass.TOTAL_INCREASING,
            mode=unit_mode,
            choice=total_unit_cfg,
        ),
        (
            SensorEntityDescription(
                key="online_devices",
                translation_key="online_devices",
                native_unit_of_measurement="devices",
                icon="mdi:devices",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            None,
        ),
        (
            SensorEntityDescription(
                key="cpu_load",
                translation_key="cpu_load",
                native_unit_of_measurement=PERCENTAGE,
                icon="mdi:cpu-64-bit",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            None,
        ),
        (
            SensorEntityDescription(
                key="memory_usage",
                translation_key="memory_usage",
                native_unit_of_measurement=PERCENTAGE,
                icon="mdi:memory",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            None,
        ),
        # Speed TOP5 intentionally has NO native_unit_of_measurement and NO
        # device_class: its existing long-term statistics are stored with
        # unit = NULL / unit_class = "unitless", and switching it to "B/s"
        # would change unit_class to "data_rate" (an incompatible statistics
        # unit change that can break/suppress long-term statistics). It exposes
        # readable values through attributes instead, so it only needs a
        # resolver for those attributes (never as a suggested unit).
        (
            SensorEntityDescription(
                key="top5_speeds",
                translation_key="top5_speeds",
                icon="mdi:speedometer",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            _UnitResolver(is_speed=True, mode=unit_mode, choice=speed_unit_cfg),
        ),
        (
            SensorEntityDescription(
                key="temperature",
                translation_key="temperature",
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
                icon="mdi:thermometer",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            None,
        ),
    ]

    for description, resolver in entity_specs:
        entities.append(
            MiWiFiRouterSensor(
                coordinator=coordinator,
                description=description,
                resolver=resolver,
                model=api.model,
                firmware=api.firmware,
            )
        )

    async_add_entities(entities)

    # Set up per-device sensors for tracked devices
    device_sensor_manager = MiWiFiDeviceSensorManager(
        hass, coordinator, async_add_entities, entry, api.model, api.firmware,
        unit_mode, speed_unit_cfg, total_unit_cfg,
    )

    # Register a listener to update device sensors when coordinator data changes
    entry.async_on_unload(
        coordinator.async_add_listener(device_sensor_manager.update_sensors)
    )

    # Clean up entity registry for untracked device sensors
    await _cleanup_untracked_device_sensors(hass, entry, coordinator)

    # Initial setup with current data
    device_sensor_manager.update_sensors()


async def _cleanup_untracked_device_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: MiWiFiCoordinator,
) -> None:
    """Remove entity registry entries for device sensors that are no longer tracked."""
    tracked_devices: dict[str, str] = entry.options.get(CONF_TRACKED_DEVICES, {})
    if not isinstance(tracked_devices, dict):
        tracked_devices = {}

    host = coordinator.api._host

    # Build set of expected unique_ids for currently tracked device sensors
    expected_unique_ids: set[str] = set()
    for mac in tracked_devices:
        for key, _, _, _, _ in DEVICE_SENSOR_KEYS:
            expected_unique_ids.add(f"{host}_device_{mac}_{key}")

    # Find and remove entities that belong to untracked devices
    entity_registry = async_get_entity_registry(hass)
    entities_to_remove: list[str] = []

    for entity_entry in entity_registry.entities.values():
        if (
            entity_entry.config_entry_id == entry.entry_id
            and entity_entry.domain == "sensor"
            and entity_entry.unique_id.startswith(f"{host}_device_")
            and entity_entry.unique_id not in expected_unique_ids
        ):
            entities_to_remove.append(entity_entry.entity_id)

    for entity_id in entities_to_remove:
        _LOGGER.info(
            "Removing untracked device sensor entity: %s", entity_id
        )
        entity_registry.async_remove(entity_id)


class _ByteUnitSensorMixin:
    """Shared handling of raw byte values for byte-based sensor entities."""

    _resolver: _UnitResolver

    def _apply_unit_value(
        self, raw_value: Any, extra_attributes: dict[str, Any] | None = None
    ) -> None:
        """Store the raw byte value and refresh the suggested display unit.

        ``native_value`` is always the raw byte value; Home Assistant converts
        it to the suggested (or user-overridden) display unit. ``raw_b`` and an
        auto-scaled ``human_readable`` are exposed as attributes.
        """
        resolver = self._resolver
        raw = _as_int(raw_value)
        value, display_unit = resolver.process(raw)
        self._attr_native_value = value
        if _HAS_SUGGESTED_UNIT and display_unit is not None:
            # Publishes the new display unit; history/statistics are unaffected.
            self._attr_suggested_unit_of_measurement = display_unit

        attributes: dict[str, Any] = dict(extra_attributes or {})
        attributes["raw_b"] = raw
        attributes["human_readable"] = _human_readable(raw, resolver.is_speed, resolver.mode)
        attributes["display_unit"] = display_unit or resolver.native_unit
        self._attr_extra_state_attributes = attributes


class MiWiFiRouterSensor(
    _ByteUnitSensorMixin, CoordinatorEntity[MiWiFiCoordinator], SensorEntity
):
    """Representation of a MiWiFi Router sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MiWiFiCoordinator,
        description: SensorEntityDescription,
        resolver: _UnitResolver | None,
        model: str,
        firmware: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._model = model
        self._firmware = firmware
        self._attr_unique_id = f"{coordinator.api._host}_{description.key}"
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        if resolver is not None:
            self._resolver = resolver
        if _HAS_SUGGESTED_UNIT:
            suggested = getattr(description, "suggested_unit_of_measurement", None)
            if suggested is not None:
                self._attr_suggested_unit_of_measurement = suggested

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for the router."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.api._host)},
            "name": self._model or "MiWiFi Router",
            "manufacturer": "Xiaomi",
            "model": self._model,
            "sw_version": self._firmware,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.router_data
        status = data.status

        key = self.entity_description.key

        if key in _UNIT_SENSOR_FIELDS:
            # Speed/total sensors: report raw bytes, the display conversion is
            # done by Home Assistant through device_class + suggested unit.
            raw = status.get("wan", {}).get(_UNIT_SENSOR_FIELDS[key], 0)
            self._apply_unit_value(raw)

        elif key == "online_devices":
            online = status.get("count", {}).get("online", 0)
            total = status.get("count", {}).get("all", 0)
            self._attr_native_value = online
            self._attr_extra_state_attributes = {
                "total_devices": total,
                "offline_devices": max(0, total - online),
            }

        elif key == "cpu_load":
            cpu = status.get("cpu", {})
            load = cpu.get("load", 0)
            # CPU load is a ratio (0-1), convert to percentage
            if isinstance(load, (int, float)) and 0 < load <= 1:
                load = round(load * 100, 1)
            elif isinstance(load, (int, float)) and load > 1:
                load = round(load, 1)
            self._attr_native_value = load
            self._attr_extra_state_attributes = {
                "cores": cpu.get("core", 0),
                "frequency": cpu.get("hz", ""),
            }

        elif key == "memory_usage":
            mem = status.get("mem", {})
            usage = mem.get("usage", 0)
            # Memory usage is a ratio (0-1), convert to percentage
            if isinstance(usage, (int, float)) and 0 < usage <= 1:
                usage = round(usage * 100, 1)
            elif isinstance(usage, (int, float)) and usage > 1:
                usage = round(usage, 1)
            self._attr_native_value = usage
            self._attr_extra_state_attributes = {
                "total_memory": mem.get("total", ""),
            }

        elif key == "top5_speeds":
            top5 = data.get_top5_speeds()
            if top5:
                top1 = top5[0]
                raw_speed = _as_int(top1.get("total_speed", 0))
                display_value, display_unit = self._resolver.display_pair(raw_speed)
                self._attr_native_value = raw_speed
                self._attr_extra_state_attributes = {
                    "top5": top5,
                    "top5_human": [
                        f"{d['name']}: {d['total_speed_human']} (↓{d['downspeed_human']} ↑{d['upspeed_human']})"
                        for d in top5
                    ],
                    "raw_b": raw_speed,
                    "human_readable": _human_readable(
                        raw_speed, True, self._resolver.mode
                    ),
                    "display_value": display_value,
                    "display_unit": display_unit,
                }
            else:
                self._attr_native_value = 0
                self._attr_extra_state_attributes = {
                    "top5": [],
                    "top5_human": [],
                    "raw_b": 0,
                    "human_readable": _human_readable(0, True, self._resolver.mode),
                    "display_value": 0,
                    "display_unit": units.base_unit(True, self._resolver.mode),
                }

        elif key == "temperature":
            temp = status.get("temperature", 0)
            # Temperature of 0 means the router has no temperature sensor
            if temp and isinstance(temp, (int, float)) and temp > 0:
                self._attr_native_value = round(float(temp), 1)
            else:
                self._attr_native_value = None

        self.async_write_ha_state()


class MiWiFiDeviceSensorManager:
    """Manages per-device sensor entities based on tracked_devices config.

    Only devices selected in the Options flow will have sensor entities created.
    Each tracked device gets 4 sensors: download_speed, upload_speed,
    download_total, upload_total.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: MiWiFiCoordinator,
        async_add_entities: AddEntitiesCallback,
        entry: ConfigEntry,
        model: str,
        firmware: str,
        unit_mode: str,
        speed_unit_cfg: str,
        total_unit_cfg: str,
    ) -> None:
        """Initialize the per-device sensor manager."""
        self._hass = hass
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._entry = entry
        self._model = model
        self._firmware = firmware
        self._unit_mode = unit_mode
        self._speed_unit_cfg = speed_unit_cfg
        self._total_unit_cfg = total_unit_cfg
        # MAC → {sensor_key: MiWiFiDeviceSensor}
        self._known_sensors: dict[str, dict[str, MiWiFiDeviceSensor]] = {}

    def _get_tracked_devices(self) -> dict[str, str]:
        """Get tracked devices from config entry options.

        Returns dict of {mac: device_name}.
        """
        tracked = self._entry.options.get(CONF_TRACKED_DEVICES, {})
        if isinstance(tracked, dict):
            return tracked
        return {}

    def update_sensors(self) -> None:
        """Create/update per-device sensors based on config and coordinator data."""
        tracked_devices = self._get_tracked_devices()

        new_entities: list[MiWiFiDeviceSensor] = []

        for mac, device_name in tracked_devices.items():
            if mac not in self._known_sensors:
                # Create sensors for this tracked device
                self._known_sensors[mac] = {}

                for key, translation_key, is_speed, icon, state_class in DEVICE_SENSOR_KEYS:
                    description, resolver = _build_unit_description(
                        key=key,
                        translation_key=translation_key,
                        is_speed=is_speed,
                        icon=icon,
                        state_class=state_class,
                        mode=self._unit_mode,
                        choice=(
                            self._speed_unit_cfg if is_speed else self._total_unit_cfg
                        ),
                    )
                    sensor = MiWiFiDeviceSensor(
                        coordinator=self._coordinator,
                        mac=mac,
                        device_name=device_name,
                        description=description,
                        resolver=resolver,
                        model=self._model,
                        firmware=self._firmware,
                        is_speed=is_speed,
                    )
                    self._known_sensors[mac][key] = sensor
                    new_entities.append(sensor)

        if new_entities:
            self._async_add_entities(new_entities, update_before_add=True)


class MiWiFiDeviceSensor(
    _ByteUnitSensorMixin, CoordinatorEntity[MiWiFiCoordinator], SensorEntity
):
    """Per-device speed/traffic sensor.

    Each tracked device gets 4 sensor entities:
    - Device Download Speed (raw B/s, device_class DATA_RATE, measurement)
    - Device Upload Speed (raw B/s, device_class DATA_RATE, measurement)
    - Device Download Total (raw B, device_class DATA_SIZE, total_increasing)
    - Device Upload Total (raw B, device_class DATA_SIZE, total_increasing)

    The display unit is suggested through the entity description and converted
    by Home Assistant, so changing units never recreates these entities.

    Entity name is "{device_name} {translated_suffix}" e.g. "我的手机 下载速率".
    has_entity_name=False because device_info points to the router, not the
    individual device. We set _attr_name manually using translation_key.
    """

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: MiWiFiCoordinator,
        mac: str,
        device_name: str,
        description: SensorEntityDescription,
        resolver: _UnitResolver,
        model: str,
        firmware: str,
        is_speed: bool,
    ) -> None:
        """Initialize the per-device sensor."""
        super().__init__(coordinator)
        self._mac = mac
        self._device_name = device_name
        self.entity_description = description
        self._model = model
        self._firmware = firmware
        self._resolver = resolver
        self._is_speed = is_speed
        self._attr_unique_id = (
            f"{coordinator.api._host}_device_{mac}_{description.key}"
        )
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        if _HAS_SUGGESTED_UNIT:
            suggested = getattr(description, "suggested_unit_of_measurement", None)
            if suggested is not None:
                self._attr_suggested_unit_of_measurement = suggested
        # Placeholder name; will be updated with translated suffix in
        # async_added_to_hass when hass is available for translation lookup.
        self._attr_name = device_name

    async def async_added_to_hass(self) -> None:
        """Set translated entity name when added to hass.

        Uses HA's translation system to resolve the translation_key from
        the entity_description. Falls back to English if translation
        is not found.
        """
        await super().async_added_to_hass()

        translation_key = self.entity_description.translation_key
        if translation_key:
            try:
                translations = await translation.async_get_translations(
                    self.hass,
                    self.hass.config.language,
                    "entity",
                    [DOMAIN],
                )
                full_key = f"component.{DOMAIN}.entity.sensor.{translation_key}.name"
                translated_name = translations.get(full_key)
                if translated_name:
                    self._attr_name = f"{self._device_name} {translated_name}"
                else:
                    fallback = translation_key.replace("_", " ").title()
                    self._attr_name = f"{self._device_name} {fallback}"
            except Exception:
                fallback = translation_key.replace("_", " ").title()
                self._attr_name = f"{self._device_name} {fallback}"

        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for the router."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.api._host)},
            "name": self._model or "MiWiFi Router",
            "manufacturer": "Xiaomi",
            "model": self._model,
            "sw_version": self._firmware,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Device sensors are available even when the device is offline,
        as long as the coordinator update was successful (we keep
        the last known value).
        """
        return self.coordinator.last_update_success

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        devices = self.coordinator.router_data.devices
        if self._mac in devices:
            dev_data = devices[self._mac]
            key = self.entity_description.key
            # Device context shared by all per-device sensor variants:
            # mac/ip let users identify the device behind generic names.
            device_attrs = {
                "mac": self._mac,
                "ip": dev_data.get("ip", ""),
            }

            if key in _DEVICE_UNIT_FIELDS:
                # Raw byte value; HA converts it to the suggested display unit.
                self._apply_unit_value(
                    dev_data.get(_DEVICE_UNIT_FIELDS[key], 0), device_attrs
                )

        self.async_write_ha_state()
