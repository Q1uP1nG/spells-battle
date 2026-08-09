from dataclasses import dataclass

import numpy as np


@dataclass
class Particle:
    pos: np.ndarray
    vel: np.ndarray
    color: tuple
    radius: float
    life: float
    max_life: float
    kind: str = "dot"
