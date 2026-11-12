"""D3-003.2 — scale-up/down cooldown + hard bounds, all pure functions.

Asymmetric §9 Decision 4 cooldowns (up 30 s, down 300 s): react up fast,
shrink down slowly, so oscillating forecasts cannot flap the workload.
Bounds clamp happens HERE (before any API call, PS-3); the server boundary
re-clamps again independently (defense in depth, D3-003.4).

No clock reads, no RNG, no I/O: the caller passes `now` and the persisted
state, so replays are deterministic (PS-2/PS-4).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class CooldownState:
    """What the controller remembers about its last action (pure state)."""

    last_scale_ts: float | None = None
    last_replicas: int | None = None     # last applied (post-bound) replicas
    last_direction: str | None = None    # "up" | "down" | None


def resolve_direction(target: int, state: CooldownState) -> str:
    """Direction of the proposed move relative to the last applied count."""
    if state.last_replicas is None:
        return "up"                       # first action is handled like a scale-up
    if target > state.last_replicas:
        return "up"
    if target < state.last_replicas:
        return "down"
    return "none"


def gate_scale(
    target: int,
    state: CooldownState,
    now_ts: float,
    *,
    up_s: int | None = None,
    down_s: int | None = None,
) -> tuple[bool, str]:
    """Cooldown check: `(allowed, reason)`. `target == last` → no scale needed.

    A scale is allowed when no previous action exists, when it equals the last
    applied count (no-op, never throttled), or when `now` has cleared the
    direction's window (up 30 s / down 300 s, §9 Decision 4).
    """
    up = int(config.COOLDOWN_UP_S if up_s is None else up_s)
    down = int(config.COOLDOWN_DOWN_S if down_s is None else down_s)
    direction = resolve_direction(target, state)
    if direction == "none":
        return True, "no_change"
    if state.last_scale_ts is None:
        return True, f"{direction}_first_action"
    elapsed = float(now_ts) - float(state.last_scale_ts)
    window = float(up if direction == "up" else down)
    if elapsed >= window:
        return True, f"{direction}_after_cooldown:{elapsed:.0f}s_ge_{window:.0f}s"
    return False, f"{direction}_cooldown_blocked:{elapsed:.0f}s_lt_{window:.0f}s"


def clamp_bounds(target: int, *, bounds: tuple[int, int] | None = None) -> tuple[int, bool]:
    """Clamp to [min, max] BEFORE any API call (PS-3). Returns (value, clamped)."""
    if bounds is None:
        lo, hi = config.MIN_REPLICAS, config.MAX_REPLICAS
    else:
        lo, hi = int(bounds[0]), int(bounds[1])
    if lo > hi:
        raise ValueError(f"bounds min > max: {(lo, hi)!r}")
    if target < lo or target > hi:
        return int(min(max(int(target), lo), hi)), True
    return int(target), False


__all__ = ["CooldownState", "resolve_direction", "gate_scale", "clamp_bounds"]
