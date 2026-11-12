"""Module 5 — capacity forecasting + baselines (D3-002).

Public surface:
    SeasonalForecaster       main seasonal forecast (harmonic default, Prophet optional)
    ForecastResult           per-path values + model label + documented fallback
    SeasonalNaive, TreeBaseline, Persistence   Contract-A baselines / fallback
    seasonality_gate, GateResult               D3-002.4 gate
    service_series, backtest_anchors, compare_models, assert_main_beats_baselines
    run_forecast, ServiceForecast, ForecastRun
    inference_rows, write_forecast             Contract-A writers

Offline check: ``python -m aiops.forecast --selftest``.
"""
from __future__ import annotations

from . import config
from .baselines import Persistence, SeasonalNaive, TreeBaseline
from .gate import GateResult, seasonality_gate
from .inference import KINDS, MODULE, inference_rows, write_forecast
from .model import (
    HARMONIC_MODEL,
    PERSISTENCE_MODEL,
    PROPHET_MODEL,
    SNAIVE_FALLBACK_MODEL,
    SNAIVE_MODEL,
    ForecastResult,
    SeasonalForecaster,
)
from .pipeline import (
    N_BACKTEST_ANCHORS,
    ServiceForecast,
    ForecastRun,
    assert_main_beats_baselines,
    backtest_anchors,
    compare_models,
    run_forecast,
    service_series,
)

__all__ = [
    "config",
    "MODULE",
    "KINDS",
    "HARMONIC_MODEL",
    "PROPHET_MODEL",
    "SNAIVE_MODEL",
    "SNAIVE_FALLBACK_MODEL",
    "PERSISTENCE_MODEL",
    "ForecastResult",
    "ForecastRun",
    "GateResult",
    "N_BACKTEST_ANCHORS",
    "Persistence",
    "SeasonalForecaster",
    "SeasonalNaive",
    "ServiceForecast",
    "TreeBaseline",
    "assert_main_beats_baselines",
    "backtest_anchors",
    "compare_models",
    "inference_rows",
    "run_forecast",
    "service_series",
    "seasonality_gate",
    "write_forecast",
]
