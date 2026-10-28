"""Chronological holdout, embargo and infected-period exclusion (TS-3).

The D3-001 methodology is deliberately strict:

* the split is by timestamp, never shuffled;
* an ``H``-second embargo removes any training row whose forward label window
  reaches into the test period;
* injected-fault ("infected") periods can be removed from training, including
  rows *before* the period whose labels overlap it.

A violated chronology must fail loudly rather than silently produce a leaky
result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from . import config

KEY_COLUMNS = ["ts", "service"]


@dataclass(frozen=True)
class ChronoSplit:
    train: pd.DataFrame
    test: pd.DataFrame
    cut_ts: float
    horizon_s: int


def chrono_split(
    frame: pd.DataFrame,
    train_frac: float | None = None,
    horizon_s: int | float | None = None,
    time_col: str = "ts",
) -> ChronoSplit:
    """Split a feature/label frame into chronological train and test sets.

    ``train_frac`` is applied to *unique timestamps*, so all services share one
    boundary and a cut landing on a shared timestamp moves every row at that
    timestamp into the test side.
    """
    if frame is None or frame.empty:
        raise ValueError("cannot split an empty frame")
    if time_col not in frame.columns:
        raise ValueError(f"missing time column: {time_col}")
    frac = float(config.TRAIN_FRAC if train_frac is None else train_frac)
    horizon = int(config.HORIZON_S if horizon_s is None else horizon_s)
    if not 0.0 < frac < 1.0:
        raise ValueError(f"train_frac must be in (0, 1), got {frac}")
    if horizon < 0:
        raise ValueError(f"horizon_s must be >= 0, got {horizon}")

    work = frame.copy()
    work[time_col] = pd.to_numeric(work[time_col], errors="raise").astype(float)
    if not np.isfinite(work[time_col]).all():
        raise ValueError("non-finite timestamps cannot be split chronologically")
    unique_ts = np.sort(work[time_col].unique())
    if len(unique_ts) < 2:
        raise ValueError("need at least two distinct timestamps to split")

    cut_idx = int(np.floor(len(unique_ts) * frac))
    cut_idx = min(max(cut_idx, 1), len(unique_ts) - 1)
    cut_ts = float(unique_ts[cut_idx])

    train_all = work[work[time_col] < cut_ts]
    test = work[work[time_col] >= cut_ts]
    if train_all.empty or test.empty:
        raise ValueError("chronological split produced an empty side")

    # (t, t+H] must not touch the test period: require t + H < cut.
    train = train_all[train_all[time_col] + horizon < cut_ts]
    if train.empty:
        raise ValueError("embargo removed every training row; collect more history")

    train = train.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    test = test.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    _assert_chronology(train, test, horizon, time_col)
    return ChronoSplit(train=train, test=test, cut_ts=cut_ts, horizon_s=horizon)


def _assert_chronology(
    train: pd.DataFrame,
    test: pd.DataFrame,
    horizon_s: int | float,
    time_col: str = "ts",
) -> None:
    if train.empty or test.empty:
        raise ValueError("chronology check needs non-empty train and test")
    train_max = float(train[time_col].max())
    test_min = float(test[time_col].min())
    if not train_max + float(horizon_s) < test_min:
        raise ValueError(
            "chronology violation: training labels reach into the test period "
            f"(train_max={train_max}, horizon={horizon_s}, test_min={test_min})"
        )


def exclude_infected(
    frame: pd.DataFrame,
    windows: Iterable[Sequence[float]] | None,
    horizon_s: int | float = 0,
    time_col: str = "ts",
) -> pd.DataFrame:
    """Drop rows whose timestamp **or forward label window** hits an infected period.

    ``windows`` is an iterable of inclusive ``(start_ts, end_ts)`` epoch-second
    intervals recorded by the experiment ledger.  Passing ``horizon_s=H`` also
    removes pre-period rows whose labels could have been caused by the injected
    fault; leaving it at 0 filters only rows inside the period.
    """
    if frame is None:
        raise ValueError("cannot exclude infected periods from a None frame")
    if time_col not in frame.columns:
        raise ValueError(f"missing time column: {time_col}")
    windows = list(windows or [])
    if not windows:
        return frame.copy()
    horizon = float(horizon_s)
    if horizon < 0:
        raise ValueError(f"horizon_s must be >= 0, got {horizon}")

    times = pd.to_numeric(frame[time_col], errors="raise").astype(float).to_numpy()
    drop = np.zeros(len(frame), dtype=bool)
    for window in windows:
        if len(window) != 2:
            raise ValueError(f"infected window must be (start, end), got {window!r}")
        start, end = float(window[0]), float(window[1])
        if not np.isfinite(start) or not np.isfinite(end):
            raise ValueError(f"infected window must be finite, got {window!r}")
        if start > end:
            raise ValueError(f"infected window start > end: {window!r}")
        # A row is infected if its own timestamp is in the window, or (when a
        # horizon is supplied) its forward label window overlaps the window.
        drop |= (times >= start) & (times <= end)
        if horizon > 0:
            drop |= (times <= end) & (times + horizon >= start)

    return frame.loc[~drop].reset_index(drop=True)


def assert_no_infected(
    frame: pd.DataFrame,
    windows: Iterable[Sequence[float]] | None,
    horizon_s: int | float = 0,
    time_col: str = "ts",
) -> None:
    """Raise if any row still overlaps an infected window (test/audit helper)."""
    windows = list(windows or [])
    if not windows or frame.empty:
        return
    times = pd.to_numeric(frame[time_col], errors="raise").astype(float).to_numpy()
    horizon = float(horizon_s)
    for window in windows:
        start, end = float(window[0]), float(window[1])
        hit = (times >= start) & (times <= end)
        if horizon > 0:
            hit |= (times <= end) & (times + horizon >= start)
        if hit.any():
            raise ValueError(
                f"infected rows remain for window ({start}, {end}): "
                f"{int(hit.sum())} row(s)"
            )
