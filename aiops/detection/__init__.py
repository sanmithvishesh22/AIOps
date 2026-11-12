"""Module 1 — anomaly detection (ticket B2).

Public surface:
    detect()          — Isolation Forest detector
    ensemble_blending — score_frame from LSTM + IF, blend_scores
    anomaly_threshold — default 0.8
"""
from __future__ import annotations

from .__main__ import FEATURES, detect
from .ensemble import blend_scores
from .lstm_autoencoder import LSTMAutoencoder, reconstruction_errors, score_frame as lstm_score_frame

__all__ = [
    "FEATURES",
    "detect",
    "blend_scores",
    "LSTMAutoencoder",
    "reconstruction_errors",
    "lstm_score_frame",
]