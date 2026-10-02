"""Unit helpers for the MiWiFi Router integration.

This module is deliberately free of Home Assistant imports: it is plain Python
(standard library only) so the unit logic can be exercised without a Home
Assistant installation.

Design notes
------------
* Sensor *native* units are always raw bytes: ``B/s`` for speeds and ``B`` for
  total traffic. The raw byte value is what feeds long-term statistics, so it
  never changes when the user switches the display unit.
* ``unit_mode`` selects the *display* family: ``byte`` (B/s, MB/s, GB, ...) or
  ``bit`` (bit/s, Mbit/s, Gbit, ...). Display conversion itself is performed by
  Home Assistant through ``SensorEntityDescription.
  suggested_unit_of_measurement`` plus the ``device_class``.
* :func:`resolve_unit` turns an option value into a display unit of the
  requested family. It returns ``None`` for "auto" (auto-scaling) and for any
  choice that does not belong to the requested family, so a stale option value
  can never produce an invalid native/display unit pair.
* :class:`AutoUnitScaler` and :func:`auto_size_unit` pick readable display units
  from observed raw values.
"""

from __future__ import annotations

import math
import time

UNIT_MODE_BYTE = "byte"
UNIT_MODE_BIT = "bit"

#: Option value meaning "pick a readable unit automatically".
AUTO_CHOICE = "auto"

# Byte families (SI 1000-based and IEC 1024-based units).
RATE_UNITS_BYTE = ("B/s", "kB/s", "MB/s", "GB/s", "KiB/s", "MiB/s", "GiB/s")
SIZE_UNITS_BYTE = ("B", "kB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB")

# Bit families.
RATE_UNITS_BIT = ("bit/s", "kbit/s", "Mbit/s", "Gbit/s")
SIZE_UNITS_BIT = ("bit", "kbit", "Mbit", "Gbit")

#: Bytes per second for one unit of the key (``bit/s`` == 0.125 B/s).
RATE_UNIT_FACTORS: dict[str, float] = {
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

#: Bytes per one unit of the key (``bit`` == 0.125 B).
SIZE_UNIT_FACTORS: dict[str, float] = {
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

# SI-scaled ladders used for automatic (readable) unit selection.
_AUTO_RATE_UNITS_BYTE = ("B/s", "kB/s", "MB/s", "GB/s")
_AUTO_SIZE_UNITS_BYTE = ("B", "kB", "MB", "GB", "TB")
_AUTO_RATE_UNITS_BIT = ("bit/s", "kbit/s", "Mbit/s", "Gbit/s")
_AUTO_SIZE_UNITS_BIT = ("bit", "kbit", "Mbit", "Gbit")

# Hysteresis band, expressed in *current unit* terms, and default dwell time.
_HYSTERESIS_LOW = 0.5
_HYSTERESIS_HIGH = 2000.0
# Number of recent samples used as the representative value (~30 s at the
# default 5 s poll interval) and the minimum time before the unit may switch
# *down* again.
_DEFAULT_WINDOW = 6
_DEFAULT_MIN_DWELL_S = 60.0


def _normalise_mode(mode: str | None) -> str:
    """Return a valid unit mode, defaulting to the byte family."""
    return UNIT_MODE_BIT if mode == UNIT_MODE_BIT else UNIT_MODE_BYTE


def _to_float(value: object) -> float:
    """Coerce an arbitrary value to a finite float; never raises."""
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return number


def units_for(mode: str, is_speed: bool) -> tuple[str, ...]:
    """Return every unit of ``mode``'s family for speeds or totals."""
    if _normalise_mode(mode) == UNIT_MODE_BIT:
        return RATE_UNITS_BIT if is_speed else SIZE_UNITS_BIT
    return RATE_UNITS_BYTE if is_speed else SIZE_UNITS_BYTE


def auto_unit_ladder(mode: str, is_speed: bool) -> tuple[str, ...]:
    """Return the SI-scaled unit ladder used for automatic unit selection."""
    if _normalise_mode(mode) == UNIT_MODE_BIT:
        return _AUTO_RATE_UNITS_BIT if is_speed else _AUTO_SIZE_UNITS_BIT
    return _AUTO_RATE_UNITS_BYTE if is_speed else _AUTO_SIZE_UNITS_BYTE


def base_unit(is_speed: bool, mode: str = UNIT_MODE_BYTE) -> str:
    """Return the smallest unit of the requested family."""
    return auto_unit_ladder(mode, is_speed)[0]


def native_unit(is_speed: bool) -> str:
    """Return the fixed raw-byte native unit for speeds or totals.

    The native unit never depends on the unit mode: raw bytes are the basis of
    Home Assistant long-term statistics.
    """
    return "B/s" if is_speed else "B"


def factors_for(is_speed: bool) -> dict[str, float]:
    """Return the byte-factor table used to convert ``is_speed`` values."""
    return RATE_UNIT_FACTORS if is_speed else SIZE_UNIT_FACTORS


def resolve_unit(mode: str, choice: str | None, is_speed: bool) -> str | None:
    """Resolve an explicit/auto unit choice into a display unit.

    Returns ``None`` for "auto" (callers then use auto-scaling) and for any
    choice that is unknown or belongs to the other family, so a stale option
    value (e.g. ``"MB/s"`` while ``mode == "bit"``) can never build an invalid
    native/display unit pair.
    """
    if not choice or choice == AUTO_CHOICE:
        return None
    if choice in units_for(mode, is_speed):
        return choice
    return None


def convert_from_bytes(value: float, unit: str) -> float:
    """Convert a raw byte value (or B/s) into ``unit``; never raises."""
    number = _to_float(value)
    factor = RATE_UNIT_FACTORS.get(unit)
    if factor is None:
        factor = SIZE_UNIT_FACTORS.get(unit)
    if not factor:
        return number
    return number / factor


def pick_readable_unit(
    value: float, mode: str = UNIT_MODE_BYTE, is_speed: bool = True
) -> str:
    """Pick the SI-scaled unit where ``value`` lands in [1, 1000) (best effort)."""
    number = abs(_to_float(value))
    ladder = auto_unit_ladder(mode, is_speed)
    factors = factors_for(is_speed)
    chosen = ladder[0]
    for unit in ladder[1:]:
        if number >= factors[unit]:
            chosen = unit
        else:
            break
    return chosen


def auto_size_unit(bytes_value: float, mode: str = UNIT_MODE_BYTE) -> str:
    """Pick a stable display unit for a total (monotonic) traffic value.

    Used once per total sensor: totals feed ``TOTAL_INCREASING`` statistics and
    must not switch their display unit back and forth.
    """
    return pick_readable_unit(bytes_value, mode, is_speed=False)


def _format_scaled(value: float, unit: str) -> str:
    """Format a scaled numeric value with a readable number of decimals."""
    number = _to_float(value)
    if number == 0:
        return f"0 {unit}"
    magnitude = abs(number)
    if magnitude >= 100:
        text = f"{number:.0f}"
    elif magnitude >= 10:
        text = f"{number:.1f}"
    else:
        text = f"{number:.2f}"
    return f"{text} {unit}"


def human_readable_rate(bytes_per_s: float, mode: str = UNIT_MODE_BYTE) -> str:
    """Format a raw byte/second value as a readable string, e.g. "2.45 MB/s".

    Safe for ``None``, negative and huge input; never raises.
    """
    number = _to_float(bytes_per_s)
    unit = pick_readable_unit(number, mode, is_speed=True)
    return _format_scaled(convert_from_bytes(number, unit), unit)


def human_readable_size(bytes_value: float, mode: str = UNIT_MODE_BYTE) -> str:
    """Format a raw byte total as a readable string, e.g. "1.23 GB".

    Safe for ``None``, negative and huge input; never raises.
    """
    number = _to_float(bytes_value)
    unit = pick_readable_unit(number, mode, is_speed=False)
    return _format_scaled(convert_from_bytes(number, unit), unit)


class AutoUnitScaler:
    """Pick a readable display unit from observed raw values (bytes or B/s).

    - keeps a rolling window of recent raw samples (default 6, i.e. roughly the
      last 30 s at the default 5 s poll interval)
    - uses the peak of that window as the representative value and picks the
      unit where it lands in [1, 1000). Using the peak (instead of e.g. the
      mean/median) keeps the unit stable for bursty traffic: one busy sample
      holds the readable unit for the whole window instead of the unit
      flip-flopping between decades sample by sample.
    - hysteresis: only switches when the value leaves a wide band
      ([0.5, 2000) expressed in current-unit terms) to avoid flapping
    - switching *up* to a bigger unit happens immediately (readability), while
      switching *down* waits for ``min_dwell_s`` (default 60 s); a completely
      idle window decays back to the family's base unit after the same dwell
    - an already stored display unit can be adopted through :meth:`adopt`, so a
      reload/restart continues with the unit the user last saw
    """

    def __init__(
        self,
        *,
        is_speed: bool,
        mode: str = UNIT_MODE_BYTE,
        window: int = _DEFAULT_WINDOW,
        min_dwell_s: float = _DEFAULT_MIN_DWELL_S,
        initial: str | None = None,
    ) -> None:
        """Initialize the scaler for one sensor entity."""
        self._is_speed = is_speed
        self._mode = _normalise_mode(mode)
        try:
            self._window = max(1, int(window))
        except (TypeError, ValueError):
            self._window = _DEFAULT_WINDOW
        self._min_dwell_s = max(0.0, _to_float(min_dwell_s))
        self._samples: list[float] = []
        ladder = auto_unit_ladder(self._mode, is_speed)
        self._unit = initial if initial in ladder else ladder[0]
        self._last_switch: float | None = None

    @property
    def unit(self) -> str:
        """Return the currently suggested display unit."""
        return self._unit

    def adopt(self, unit: str | None) -> bool:
        """Adopt an already stored display unit as the starting point.

        Home Assistant keeps the display unit of an entity in the entity
        registry. When the platform is set up again (reload/restart) the scaler
        is re-created, and without adopting the stored unit the UI would fall
        back to the base unit (``B/s`` / ``bit/s``) until the scaler has
        re-learned the traffic. Returns ``True`` when ``unit`` belongs to this
        scaler's family (and was therefore adopted).
        """
        if unit in auto_unit_ladder(self._mode, self._is_speed):
            self._unit = unit
            return True
        return False

    @property
    def mode(self) -> str:
        """Return the unit family used by this scaler."""
        return self._mode

    @property
    def is_speed(self) -> bool:
        """Return whether this scaler handles a speed (True) or a total."""
        return self._is_speed

    def observe(self, raw_value: float, now: float | None = None) -> str:
        """Record a sample and return the currently suggested display unit."""
        timestamp = time.monotonic() if now is None else _to_float(now)
        self._samples.append(_to_float(raw_value))
        if len(self._samples) > self._window:
            del self._samples[0 : len(self._samples) - self._window]

        representative = self._representative()
        ladder = auto_unit_ladder(self._mode, self._is_speed)
        base = ladder[0]

        if representative <= 0:
            # Completely idle: decay to the family's base unit, but only after
            # the dwell so a short gap between bursts cannot flip the unit.
            if self._unit != base and self._dwell_elapsed(timestamp):
                self._unit = base
                self._last_switch = timestamp
            return self._unit

        suggested = pick_readable_unit(representative, self._mode, self._is_speed)
        if suggested == self._unit:
            return self._unit

        factor = factors_for(self._is_speed).get(self._unit) or 1.0
        current_value = abs(representative / factor)
        leaves_band = not (_HYSTERESIS_LOW <= current_value < _HYSTERESIS_HIGH)

        try:
            upward = ladder.index(suggested) > ladder.index(self._unit)
        except ValueError:
            upward = False

        # Growing traffic may switch up immediately (readability matters), while
        # switching down is the flicker-prone direction and keeps its dwell.
        # Without this asymmetry a single quiet sample at startup would pin the
        # display to "B/s"/"bit/s" for the whole dwell window.
        if leaves_band and (upward or self._dwell_elapsed(timestamp)):
            self._unit = suggested
            self._last_switch = timestamp
        return self._unit

    def _representative(self) -> float:
        """Return the representative value of the rolling window (its peak).

        The peak keeps the suggested unit stable for bursty traffic: as long as
        one sample of the window is fast, the readable high unit is kept, and it
        only decays once the window has drained.
        """
        if not self._samples:
            return 0.0
        return max(self._samples)

    def _dwell_elapsed(self, timestamp: float) -> bool:
        """Return whether a switch is allowed at ``timestamp``."""
        if self._last_switch is None:
            return True
        return (timestamp - self._last_switch) >= self._min_dwell_s
