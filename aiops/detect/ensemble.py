from __future__ import annotations

import sys

import numpy as np

from ..common import store
from ..ingest import sample_frame
from .__main__ import detect as iforest_score_frame
from .lstm_autoencoder import score_frame as lstm_score_frame


def _normalize_scores(scores):
    scores = np.asarray(scores, dtype=float)

    minimum = scores.min()
    maximum = scores.max()

    if maximum == minimum:
        return np.zeros_like(scores)

    return (scores - minimum) / (maximum - minimum)


def blend_scores(if_scores, lstm_scores):
    """Blend IF and LSTM-AE scores with an equal-weight average."""
    if_scores = np.asarray(if_scores, dtype=float)
    lstm_scores = np.asarray(lstm_scores, dtype=float)

    if len(if_scores) != len(lstm_scores):
        raise ValueError("detector score lengths must match")

    if_norm = _normalize_scores(if_scores)
    lstm_norm = _normalize_scores(lstm_scores)

    blended = 0.5 * if_norm + 0.5 * lstm_norm

    confidence = 1.0 - np.abs(if_norm - lstm_norm)

    return blended, confidence


def _selftest():
    # The two detectors place their strongest clean false-positive
    # on different samples. The ensemble should separate the injected
    # outlier better than either detector alone.
    if_scores = np.array([
        0.46,
        0.34,
        0.998,
        1.00,
    ])

    lstm_scores = np.array([
        0.91,
        0.22,
        0.32,
        1.00,
    ])

    blended, confidence = blend_scores(
        if_scores,
        lstm_scores,
    )

    def separation(scores):
        return float(scores[-1] - np.max(scores[:-1]))

    if_separation = separation(_normalize_scores(if_scores))
    lstm_separation = separation(_normalize_scores(lstm_scores))
    ensemble_separation = separation(blended)

    assert ensemble_separation > if_separation
    assert ensemble_separation > lstm_separation

    assert len(blended) == 4
    assert len(confidence) == 4

    # The injected outlier remains the highest-scoring point.
    assert int(np.argmax(blended)) == 3

    # Confidence is populated and bounded.
    assert np.all(confidence >= 0.0)
    assert np.all(confidence <= 1.0)

    rows = []

    for index, score in enumerate(blended):
        rows.append(
            {
                "ts": float(1000 + index),
                "module": "detect",
                "service": "orders",
                "kind": "anomaly_score",
                "value": float(score),
                "meta": {
                    "detector": "ensemble",
                    "if_score": float(if_scores[index]),
                    "lstm_score": float(lstm_scores[index]),
                    "confidence": float(confidence[index]),
                },
            }
        )

    store.normalize(rows)

    print("ensemble selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    frame = sample_frame()

    if_rows = iforest_score_frame(frame)
    lstm_rows = lstm_score_frame(frame)

    if not if_rows or not lstm_rows:
        print("no detector rows available")
        return

    print(
        f"ensemble inputs: IF={len(if_rows)}, "
        f"LSTM-AE={len(lstm_rows)}"
    )


if __name__ == "__main__":
    main()