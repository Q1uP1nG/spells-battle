import cv2
import numpy as np

from config import THEME
from renderer.text import draw_centered_text, draw_cv_text


def draw_glow_circle(frame, center, radius, color, alpha=0.35, layers=4):
    overlay = frame.copy()
    for i in range(layers, 0, -1):
        r = int(radius * i / layers)
        cv2.circle(overlay, tuple(np.int32(center)), r, color, -1, lineType=cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw_bar(frame, x, y, w, h, value, max_value, color, label, trail_value=None):
    cv2.rectangle(frame, (x, y), (x + w, y + h), THEME["panel_soft"], -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), THEME["panel_border"], 1)
    if trail_value is not None:
        trail_fill = int(w * max(0, min(1, trail_value / max_value)))
        if trail_fill > 0:
            cv2.rectangle(frame, (x, y), (x + trail_fill, y + h), THEME["hp_trail"], -1)
    fill = int(w * max(0, min(1, value / max_value)))
    if fill > 0:
        cv2.rectangle(frame, (x, y), (x + fill, y + h), color, -1)
    draw_cv_text(frame, label, (x + 8, y + h - 6), 0.45, THEME["text"])


def apply_screen_feedback(frame, game, now):
    if now < getattr(game, "screen_shake_until", 0.0):
        remaining = max(0.0, game.screen_shake_until - now)
        strength = int(max(1.0, game.screen_shake_intensity * min(1.0, remaining / 0.18)))
        dx = int(np.sin(now * 137.0) * strength)
        dy = int(np.cos(now * 173.0) * strength * 0.55)
        matrix = np.float32([[1, 0, dx], [0, 1, dy]])
        shifted = cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]), borderMode=cv2.BORDER_REFLECT)
        frame[:] = shifted

    if now < getattr(game, "hit_flash_until", 0.0):
        remaining = max(0.0, game.hit_flash_until - now)
        alpha = float(game.hit_flash_intensity) * min(1.0, remaining / 0.18)
        overlay = np.full_like(frame, THEME["flash"])
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw_shockwaves(frame, game, now):
    """Expanding rings spawned at clash / counter impacts."""
    active = []
    for wave in getattr(game, "shockwaves", []):
        duration = max(wave.get("duration", 0.45), 0.01)
        progress = (now - wave["created_at"]) / duration
        if progress >= 1.0 or progress < 0.0:
            if progress < 0.0:
                active.append(wave)
            continue
        active.append(wave)

        ease = 1.0 - (1.0 - progress) ** 2          # fast then settle
        radius = int(wave["max_radius"] * ease)
        if radius < 2:
            continue
        fade = 1.0 - progress
        center = tuple(np.int32(wave["pos"]))
        color = wave.get("color", THEME["gold_bright"])
        ring = tuple(int(min(255, c * (0.55 + 0.45 * fade))) for c in color)
        thickness = max(1, int(wave.get("thickness", 6) * fade))
        cv2.circle(frame, center, radius, ring, thickness, lineType=cv2.LINE_AA)
        # leading bright edge
        cv2.circle(frame, center, radius, (255, 255, 255), 1, lineType=cv2.LINE_AA)
        # inner companion ring for a richer pulse
        inner = int(radius * 0.62)
        if inner > 2:
            cv2.circle(frame, center, inner, ring, max(1, thickness - 2), lineType=cv2.LINE_AA)
    game.shockwaves = active


def draw_flash_messages(frame, game, now):
    active = []
    for message in getattr(game, "flash_messages", []):
        if now >= message["until"]:
            continue
        active.append(message)
        duration = max(message.get("duration", 0.8), 0.01)
        progress = max(0.0, min(1.0, (now - message["created_at"]) / duration))
        pos = message["pos"].copy()
        pos[1] -= 24 * progress
        color = message.get("color", THEME["gold_bright"])
        fade = 1.0 - progress
        draw_color = tuple(int(c * fade + 255 * (1 - fade)) for c in color)
        draw_centered_text(frame, message["text"], int(pos[0]), int(pos[1]), size=30, color=draw_color, face="title")
    game.flash_messages = active
