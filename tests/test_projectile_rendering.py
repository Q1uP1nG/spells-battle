import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ProjectileRenderingTests(unittest.TestCase):
    def _projectile(self, spell):
        from config import SPELLS
        from models.projectile import Projectile

        s = SPELLS[spell]
        return Projectile(
            owner=0,
            spell=spell,
            pos=np.array([180.0, 90.0], dtype=np.float32),
            vel=np.array([500.0, 0.0], dtype=np.float32),
            radius=s["radius"],
            damage=s["damage"],
            color=s["color"],
        )

    def test_projectile_renderer_draws_each_projectile_spell(self):
        from renderer.projectile import draw_projectile

        for spell in ("incendio", "stupefy", "glacius"):
            with self.subTest(spell=spell):
                frame = np.zeros((180, 360, 3), dtype=np.uint8)
                draw_projectile(frame, self._projectile(spell), now=10.0)

                self.assertGreater(int(np.count_nonzero(frame)), 0)


if __name__ == "__main__":
    unittest.main()
