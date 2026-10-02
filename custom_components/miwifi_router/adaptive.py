"""Adaptive polling controller for the MiWiFi router coordinator.

This module is deliberately free of any Home Assistant dependency: it is pure
standard-library Python so the whole state machine can be unit-tested outside
of Home Assistant.

Goal
----
The router is polled on a fixed cadence today (tier 1 every ``scan_interval``
seconds, tier 2 every ``device_scan_interval`` seconds). Most home networks are
idle for long stretches, so the fixed cadence mostly wastes router CPU and WiFi
airtime. This controller observes two cheap signals that are already fetched on
every tier-1 poll — WAN throughput and the set of connected device MACs — and
tells the coordinator how long it may wait before the next poll:

- ``idle``   — WAN traffic stayed at/below ``idle_traffic_bps`` for
  ``idle_samples`` consecutive samples AND the device set has been stable for
  ``device_stable_s``. Poll slowly (``idle_interval``).
- ``normal`` — default cadence (``base_interval``).
- ``active`` — a traffic burst or a device join/leave was seen. Poll quickly
  (``active_interval``) and keep doing so for ``active_hold_s`` after the last
  event, then fall back to ``normal``.

Hysteresis / storm safety
-------------------------
- Escalation into ``active`` is immediate (responsiveness matters).
- De-escalation out of a mode only happens after ``min_dwell_s`` in that mode,
  so the controller can never oscillate faster than one transition per
  ``min_dwell_s``.
- Escalation to ``active`` always resets ``idle_streak`` and ``active_until``,
  so a burst during an idle streak pushes the hold deadline further out.
- All intervals are clamped into ``[min_interval, max_interval]`` and the
  configuration is normalised in :meth:`AdaptiveConfig.normalised`, so even a
  hostile user option (0, negative, swapped values) can never produce a tight
  poll loop.
- ``update()`` never raises for a missing/explicit/non-monotonic ``now``; time
  is only ever allowed to move forward internally.
"""

from __future__ import annotations

import math
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal

PollMode = Literal["active", "normal", "idle"]

# Absolute floor/ceiling for any interval produced by this module. They are
# repeated (instead of imported from .const) on purpose: this file must stay
# importable without Home Assistant and without the rest of the integration.
_DEFAULT_MIN_INTERVAL = 5
_DEFAULT_MAX_INTERVAL = 300


def _as_int(value: Any, default: int) -> int:
    """Best-effort int conversion — never raises for hostile input."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_float(value: Any, default: float) -> float:
    """Best-effort float conversion — never raises for hostile input."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


@dataclass(frozen=True)
class AdaptiveConfig:
    """Tunable parameters for the adaptive polling state machine.

    All values are normalised by :meth:`normalised`; construct the controller
    with a raw config and it will sanitise it.
    """

    enabled: bool = True
    base_interval: int = 10          # seconds, "normal" mode (== CONF_SCAN_INTERVAL)
    idle_interval: int = 60
    active_interval: int = 5
    idle_traffic_bps: int = 1024     # <= this counts as an "idle" traffic sample
    active_traffic_bps: int = 32768  # >= this is a burst
    idle_samples: int = 6            # consecutive idle samples before sleeping
    active_hold_s: float = 60.0      # stay active this long after last burst/device event
    min_dwell_s: float = 15.0        # min time in a mode before de-escalating
    device_stable_s: float = 300.0   # device set must be stable this long before idle
    max_interval: int = 300
    min_interval: int = 5

    def normalised(self) -> AdaptiveConfig:
        """Return a copy with every field clamped into a sane range.

        Guarantees (what the coordinator and the tests rely on):

        - ``min_interval >= 1`` and ``max_interval >= min_interval``
        - ``base_interval`` inside ``[min_interval, max_interval]``
        - ``active_interval <= base_interval`` (never poll faster than the
          user's realtime interval) and ``active_interval >= min_interval``
        - ``idle_interval >= base_interval`` (idle never polls faster than
          normal) and ``idle_interval <= max_interval``
        - ``idle_traffic_bps <= active_traffic_bps`` and neither is negative
        - counters/holds are non-negative; ``idle_samples`` is at least 1
        """
        errors: list[str] = []

        min_interval = _as_int(self.min_interval, _DEFAULT_MIN_INTERVAL)
        if min_interval < 1:
            errors.append(f"min_interval {self.min_interval!r} -> 1")
            min_interval = 1

        max_interval = _as_int(self.max_interval, _DEFAULT_MAX_INTERVAL)
        if max_interval < min_interval:
            errors.append(f"max_interval {self.max_interval!r} -> {min_interval}")
            max_interval = min_interval

        base_interval = _as_int(self.base_interval, max(min_interval, 10))
        if base_interval < min_interval:
            errors.append(f"base_interval {self.base_interval!r} -> {min_interval}")
            base_interval = min_interval
        elif base_interval > max_interval:
            errors.append(f"base_interval {self.base_interval!r} -> {max_interval}")
            base_interval = max_interval

        active_interval = _as_int(self.active_interval, min_interval)
        if active_interval < min_interval:
            errors.append(f"active_interval {self.active_interval!r} -> {min_interval}")
            active_interval = min_interval
        if active_interval > base_interval:
            errors.append(
                f"active_interval {self.active_interval!r} -> {base_interval}"
            )
            active_interval = base_interval

        idle_interval = _as_int(self.idle_interval, base_interval)
        if idle_interval < base_interval:
            errors.append(f"idle_interval {self.idle_interval!r} -> {base_interval}")
            idle_interval = base_interval
        elif idle_interval > max_interval:
            errors.append(f"idle_interval {self.idle_interval!r} -> {max_interval}")
            idle_interval = max_interval

        idle_traffic_bps = _as_int(self.idle_traffic_bps, 0)
        if idle_traffic_bps < 0:
            errors.append(f"idle_traffic_bps {self.idle_traffic_bps!r} -> 0")
            idle_traffic_bps = 0

        active_traffic_bps = _as_int(self.active_traffic_bps, idle_traffic_bps)
        if active_traffic_bps < idle_traffic_bps:
            errors.append(
                f"active_traffic_bps {self.active_traffic_bps!r} -> {idle_traffic_bps}"
            )
            active_traffic_bps = idle_traffic_bps

        idle_samples = _as_int(self.idle_samples, 1)
        if idle_samples < 1:
            errors.append(f"idle_samples {self.idle_samples!r} -> 1")
            idle_samples = 1

        active_hold_s = _as_float(self.active_hold_s, 0.0)
        if active_hold_s < 0:
            errors.append(f"active_hold_s {self.active_hold_s!r} -> 0")
            active_hold_s = 0.0

        min_dwell_s = _as_float(self.min_dwell_s, 0.0)
        if min_dwell_s < 0:
            errors.append(f"min_dwell_s {self.min_dwell_s!r} -> 0")
            min_dwell_s = 0.0

        device_stable_s = _as_float(self.device_stable_s, 0.0)
        if device_stable_s < 0:
            errors.append(f"device_stable_s {self.device_stable_s!r} -> 0")
            device_stable_s = 0.0

        normalised = AdaptiveConfig(
            enabled=bool(self.enabled),
            base_interval=base_interval,
            idle_interval=idle_interval,
            active_interval=active_interval,
            idle_traffic_bps=idle_traffic_bps,
            active_traffic_bps=active_traffic_bps,
            idle_samples=idle_samples,
            active_hold_s=active_hold_s,
            min_dwell_s=min_dwell_s,
            device_stable_s=device_stable_s,
            max_interval=max_interval,
            min_interval=min_interval,
        )
        object.__setattr__(normalised, "_adjustments", tuple(errors))
        return normalised

    @property
    def adjustments(self) -> tuple[str, ...]:
        """Return the human-readable list of clamps applied by ``normalised()``."""
        return getattr(self, "_adjustments", ())


@dataclass(frozen=True)
class AdaptiveSnapshot:
    """Immutable view of the adaptive controller state."""

    mode: str
    interval: int
    base_interval: int
    idle_interval: int
    active_interval: int
    idle_streak: int
    transitions: int
    mode_since: float
    active_until: float
    last_activity_ts: float | None
    device_stable_since: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation (used by diagnostics)."""
        return {
            "mode": self.mode,
            "interval": self.interval,
            "base_interval": self.base_interval,
            "idle_interval": self.idle_interval,
            "active_interval": self.active_interval,
            "idle_streak": self.idle_streak,
            "transitions": self.transitions,
            "mode_since": self.mode_since,
            "active_until": self.active_until,
            "last_activity_ts": self.last_activity_ts,
            "device_stable_since": self.device_stable_since,
            "reason": self.reason,
        }


class AdaptivePollingController:
    """Decide the next poll interval from WAN traffic and device churn.

    The controller is intentionally a pure state machine: it has no I/O, no
    timers and no Home Assistant imports, and every decision is a function of
    ``(config, previous state, current sample, now)``.
    """

    def __init__(self, config: AdaptiveConfig) -> None:
        """Normalise and store the adaptive polling configuration."""
        self._config = config.normalised()
        self._mode: PollMode = "normal"
        self._interval: int = self._config.base_interval
        self._idle_streak: int = 0
        self._transitions: int = 0
        self._mode_since: float = 0.0
        self._active_until: float = 0.0
        self._last_activity_ts: float | None = None
        self._device_stable_since: float = 0.0
        self._has_state: bool = False
        self._prev_online_count: int | None = None
        self._prev_macs: frozenset[str] = frozenset()
        self._last_now: float | None = None
        self._last_reason: str = "quiet"
        self._snapshot = AdaptiveSnapshot(
            mode=self._mode,
            interval=self._interval,
            base_interval=self._config.base_interval,
            idle_interval=self._config.idle_interval,
            active_interval=self._config.active_interval,
            idle_streak=0,
            transitions=0,
            mode_since=0.0,
            active_until=0.0,
            last_activity_ts=None,
            device_stable_since=0.0,
            reason=self._last_reason,
        )

    # ---------------------------------------------------------------- public

    @property
    def config(self) -> AdaptiveConfig:
        """Return the normalised configuration in use."""
        return self._config

    @property
    def snapshot(self) -> AdaptiveSnapshot:
        """Return the current controller state (never recomputes time)."""
        return self._snapshot

    def update(
        self,
        *,
        wan_bps: float,
        online_count: int,
        device_macs: Collection[str],
        now: float | None = None,
    ) -> AdaptiveSnapshot:
        """Feed one poll observation and return the resulting snapshot.

        ``wan_bps`` is the current WAN throughput (download + upload, bytes per
        second), ``online_count`` the router-reported online device count and
        ``device_macs`` the MAC addresses of the currently known devices.
        ``now`` defaults to :func:`time.monotonic`; non-finite or backwards
        values are clamped so internal time only ever moves forward.
        """
        cfg = self._config

        if now is None:
            now = time.monotonic()
        else:
            now = _as_float(now, time.monotonic())
        if self._last_now is not None and now < self._last_now:
            # Non-monotonic clock (tests, clock jumps): never move backwards.
            now = self._last_now
        self._last_now = now

        wan_bps = _as_float(wan_bps, 0.0) if wan_bps is not None else 0.0
        if wan_bps < 0:
            wan_bps = 0.0
        online_count = _as_int(online_count, 0)

        macs = frozenset(
            str(mac) for mac in device_macs if mac
        )

        # --- 1. Disabled: behave exactly like the legacy fixed cadence -------
        if not cfg.enabled:
            self._remember_sample(now, online_count, macs)
            self._idle_streak = 0
            self._active_until = 0.0
            return self._emit(
                mode="normal",
                interval=cfg.base_interval,
                reason="disabled",
                mode_since=now,
                active_until=0.0,
                last_activity_ts=self._last_activity_ts,
                device_stable_since=now,
            )

        device_event = False
        burst = False

        if not self._has_state:
            # First observation: adopt the world as-is, without firing a
            # spurious "device event" for the initial device set.
            self._device_stable_since = now
            self._has_state = True
        else:
            count_changed = online_count != self._prev_online_count
            macs_changed = macs != self._prev_macs
            if count_changed or macs_changed:
                device_event = True
                self._last_activity_ts = now
                self._device_stable_since = now
                self._idle_streak = 0

        self._prev_online_count = online_count
        self._prev_macs = macs
        self._has_state = True

        # --- 2. Classify traffic ------------------------------------------
        if wan_bps >= cfg.active_traffic_bps:
            burst = True
            self._idle_streak = 0
            self._last_activity_ts = now
        elif wan_bps > cfg.idle_traffic_bps:
            # Light activity: not a burst, but not idle either.
            self._idle_streak = 0
            self._last_activity_ts = now
        else:
            self._idle_streak += 1

        # --- 3. Desired mode ----------------------------------------------
        if burst or device_event:
            desired: PollMode = "active"
            reason = "burst" if burst else "device_event"
            self._active_until = now + cfg.active_hold_s
        elif self._mode == "active" and now < self._active_until:
            desired = "active"
            reason = "hold"
        elif (
            self._idle_streak >= cfg.idle_samples
            and (now - self._device_stable_since) >= cfg.device_stable_s
            and now >= self._active_until
        ):
            desired = "idle"
            reason = "idle_streak"
        else:
            desired = "normal"
            if self._active_until > now:
                reason = "hold"
            elif self._idle_streak < cfg.idle_samples:
                reason = "quiet"
            elif (now - self._device_stable_since) < cfg.device_stable_s:
                reason = "device_stable"
            else:
                reason = "quiet"

        # --- 4. Apply hysteresis ------------------------------------------
        mode = self._mode
        if desired != mode:
            escalating = desired == "active"
            dwell_elapsed = (now - self._mode_since) >= cfg.min_dwell_s
            if escalating or dwell_elapsed or self._transitions == 0:
                # Escalation into active is immediate; de-escalation must
                # respect min_dwell so modes cannot flap.
                mode = desired
                self._mode_since = now
                self._transitions += 1
            else:
                # Keep the current mode for now; remember why we wanted to
                # leave so diagnostics can show the blocker.
                reason = "min_dwell"

        self._mode = mode
        interval = {
            "active": cfg.active_interval,
            "idle": cfg.idle_interval,
            "normal": cfg.base_interval,
        }[mode]
        interval = max(cfg.min_interval, min(cfg.max_interval, interval))

        return self._emit(
            mode=mode,
            interval=interval,
            reason=reason,
            mode_since=self._mode_since,
            active_until=self._active_until,
            last_activity_ts=self._last_activity_ts,
            device_stable_since=self._device_stable_since,
        )

    # --------------------------------------------------------------- private

    def _remember_sample(
        self, now: float, online_count: int, macs: frozenset[str]
    ) -> None:
        """Update the observation windows without touching mode state."""
        self._has_state = True
        self._prev_online_count = online_count
        self._prev_macs = macs

    def _emit(
        self,
        *,
        mode: PollMode,
        interval: int,
        reason: str,
        mode_since: float,
        active_until: float,
        last_activity_ts: float | None,
        device_stable_since: float,
    ) -> AdaptiveSnapshot:
        """Store and return the new immutable snapshot."""
        self._interval = interval
        self._last_reason = reason
        cfg = self._config
        self._snapshot = AdaptiveSnapshot(
            mode=mode,
            interval=interval,
            base_interval=cfg.base_interval,
            idle_interval=cfg.idle_interval,
            active_interval=cfg.active_interval,
            idle_streak=self._idle_streak,
            transitions=self._transitions,
            mode_since=mode_since,
            active_until=active_until,
            last_activity_ts=last_activity_ts,
            device_stable_since=device_stable_since,
            reason=reason,
        )
        return self._snapshot
