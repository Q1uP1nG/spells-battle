"""Validation shared by gesture feature extraction and template matching."""

import numpy as np


def validated_points(points, minimum=2):
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            array = np.asarray(points, dtype=np.float32)
    except (TypeError, ValueError, OverflowError):
        return None
    if array.ndim != 2 or array.shape[1] != 2 or len(array) < minimum:
        return None
    if not np.isfinite(array).all():
        return None
    return array


def advances_toward_opponent(points, side):
    array = validated_points(points)
    if array is None or side not in ("left", "right"):
        return False
    dx = float(array[-1, 0]) - float(array[0, 0])
    return dx > 0 if side == "left" else dx < 0
