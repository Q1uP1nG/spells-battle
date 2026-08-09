"""Frame post-processing for the spell layer: motion trails + additive bloom.

This is intentionally non-invasive. Instead of rewriting every projectile and
particle renderer, we snapshot the frame *before* the spell layer is drawn and
diff against it afterwards. The positive difference is "spell light", which we
feed into a decaying trail buffer (afterimages) and a bloom pass (glow).

Usage in the render loop::

    base = postfx.snapshot(frame)   # after players/shield, before spells
    draw_projectiles(...); draw_particles(...); draw_shockwaves(...)
    postfx.render(frame, base)      # before HUD / debug text
"""

import cv2
import numpy as np


class PostFX:
    """Owns the persistent trail buffer and applies trail + bloom each frame."""

    def __init__(
        self,
        trail_decay=0.82,
        trail_strength=0.65,
        bloom_threshold=170,
        bloom_strength=0.9,
        bloom_sigma=6.0,
        bloom_scale=8,
        enabled=True,
    ):
        self.trail = None
        self.trail_decay = trail_decay
        self.trail_strength = trail_strength
        self.bloom_threshold = bloom_threshold
        self.bloom_strength = bloom_strength
        self.bloom_sigma = bloom_sigma
        self.bloom_scale = max(1, int(bloom_scale))
        self.enabled = enabled

    def snapshot(self, frame):
        """Capture the frame state just before the spell layer is drawn."""
        return frame.copy()

    def reset(self):
        self.trail = None

    def render(self, frame, base):
        """Composite decaying afterimages, then add a bloom glow in place."""
        if not self.enabled:
            return frame

        self._apply_trail(frame, base)
        self._apply_bloom(frame)
        return frame

    # -- internals ---------------------------------------------------------

    def _apply_trail(self, frame, base):
        # Positive difference == light the spell layer just added on top of base.
        delta = cv2.subtract(frame, base)

        if self.trail is None or self.trail.shape != frame.shape:
            self.trail = np.zeros_like(frame)

        # Fade existing afterimages, then composite them under the live frame.
        if self.trail_decay <= 0:
            self.trail.fill(0)
        elif self.trail_decay < 1:
            self.trail[:] = cv2.convertScaleAbs(self.trail, alpha=self.trail_decay)
        if self.trail_strength > 0:
            cv2.addWeighted(frame, 1.0, self.trail, self.trail_strength, 0, frame)

        # Inject this frame's light so it streaks on following frames.
        cv2.max(self.trail, delta, self.trail)

    def _apply_bloom(self, frame):
        if self.bloom_strength <= 0:
            return
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, self.bloom_threshold, 255, cv2.THRESH_BINARY)
        if cv2.countNonZero(mask) == 0:
            return
        bright = cv2.bitwise_and(frame, frame, mask=mask)
        small = cv2.resize(
            bright,
            (max(1, w // self.bloom_scale), max(1, h // self.bloom_scale)),
            interpolation=cv2.INTER_AREA,
        )
        small = cv2.GaussianBlur(small, (0, 0), self.bloom_sigma)
        glow = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        cv2.addWeighted(frame, 1.0, glow, self.bloom_strength, 0, frame)
