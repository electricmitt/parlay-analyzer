"""Probability recalibration (Platt-style logistic regression with regime terms).

    P_cal(over) = sigmoid(b0 + b1 * logit(p_raw) + b2 * playoff + b3 * early_season)

Fitted per market, always on predictions made strictly before the games being
calibrated (walk-forward). L2 penalty keeps regime terms at 0 when the training set
contains no examples of that regime, so the calibrator never invents a correction it
has no evidence for. Pure numpy (Newton-Raphson), deterministic.
"""
from __future__ import annotations

import numpy as np

IDENTITY = [0.0, 1.0, 0.0, 0.0]
MIN_FIT_ROWS = 1500


def _design(p: np.ndarray, playoff: np.ndarray, early: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.column_stack([np.ones_like(p), np.log(p / (1 - p)), np.asarray(playoff, float),
                            np.asarray(early, float)])


def fit(p, y, playoff, early, l2: float = 1.0, iters: int = 50) -> dict:
    """Returns {"coef": [...], "n": int}. Falls back to identity when data are scarce."""
    y = np.asarray(y, float)
    if len(y) < MIN_FIT_ROWS:
        return {"coef": list(IDENTITY), "n": int(len(y)), "fitted": False}
    X = _design(p, playoff, early)
    w = np.array(IDENTITY)
    pen = np.array([0.0, 0.0, l2, l2])  # do not shrink intercept/slope; shrink regime terms
    prior = np.array(IDENTITY)
    for _ in range(iters):
        z = X @ w
        mu = 1 / (1 + np.exp(-z))
        g = X.T @ (mu - y) + pen * (w - prior)
        H = (X * (mu * (1 - mu))[:, None]).T @ X + np.diag(pen + 1e-9)
        step = np.linalg.solve(H, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"coef": [float(c) for c in w], "n": int(len(y)), "fitted": True}


def apply(model: dict | None, p, playoff=0.0, early=0.0) -> np.ndarray:
    p_arr = np.atleast_1d(np.asarray(p, float))
    if not model:
        return p_arr
    n = len(p_arr)
    X = _design(p_arr, np.broadcast_to(playoff, n), np.broadcast_to(early, n))
    return 1 / (1 + np.exp(-(X @ np.asarray(model["coef"]))))
