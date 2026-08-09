from dataclasses import dataclass

import numpy as np


@dataclass
class Projectile:
    owner: int
    spell: str
    pos: np.ndarray
    vel: np.ndarray
    radius: float
    damage: float
    color: tuple
    life: float = 2.4
    active: bool = True
    projectile_id: int = 0
