import math

import cv2
import numpy as np

from config import SPELLS, THEME
from renderer.character_assets import draw_character_sprite
from renderer.effects import draw_glow_circle
from renderer.text import draw_cv_text


def draw_player(frame, player, now, winner=None):
    center = player.center()
    pose = player.pose_key(now, winner)
    profile = player.profile
    wand = player.wand_pos()
    body_color = profile.color if player.alive() else (70, 70, 80)
    if pose == "casting":
        body_color = tuple(min(255, int(channel * 1.25 + 35)) for channel in profile.color)
    elif pose == "hit":
        body_color = (75, 75, 245)
    elif pose == "win":
        body_color = (120, 245, 170)
    elif pose == "lose":
        body_color = (70, 70, 80)
    x1, y1, x2, y2 = player.target_body_rect()
    if pose == "casting":
        phase = 0.5 + 0.5 * math.sin(now * 18)
        draw_glow_circle(frame, center, 82 + 26 * phase, profile.color, 0.14, 4)
    asset_drawn = draw_character_sprite(
        frame,
        character_id=profile.id,
        pose=pose,
        bottom_center=(center[0], center[1] + 142),
        max_height=330,
        max_width=270,
        flip=player.side == "right",
    )

    if not asset_drawn:
        cv2.ellipse(frame, tuple(np.int32(center)), (58, 110), 0, 0, 360, body_color, 2, cv2.LINE_AA)
        cv2.circle(frame, (int(center[0]), int(center[1] - 145)), 34, body_color, 2, cv2.LINE_AA)

        hand = center + np.array([35 if player.side == "left" else -35, -35], dtype=np.float32)
        cv2.line(frame, tuple(np.int32(hand)), tuple(np.int32(wand)), (230, 230, 235), 4, cv2.LINE_AA)
        cv2.circle(frame, tuple(np.int32(wand)), 8, (255, 255, 255), -1, cv2.LINE_AA)

    draw_cv_text(frame, profile.poses[pose], (int(center[0] - 54), int(center[1] + 142)), 0.46, body_color)

    if pose == "casting":
        phase = 0.5 + 0.5 * math.sin(now * 18)
        if not asset_drawn:
            draw_glow_circle(frame, wand, 34 + 8 * phase, profile.color, 0.32, 3)
        _draw_cast_rune(frame, wand, now, profile.color, phase)

    if player.is_healing(now):
        phase = 0.5 + 0.5 * math.sin(now * 10)
        lumos_color = THEME["gold_bright"]
        draw_glow_circle(frame, center, 115 + 24 * phase, lumos_color, 0.38, 6)
        draw_glow_circle(frame, wand, 48 + 10 * phase, lumos_color, 0.45, 4)
        cv2.circle(frame, tuple(np.int32(center)), int(86 + 16 * phase), lumos_color, 2, cv2.LINE_AA)
        cv2.circle(frame, tuple(np.int32(center)), int(122 + 20 * (1 - phase)), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, tuple(np.int32(wand)), tuple(np.int32(center)), lumos_color, 2, cv2.LINE_AA)
        draw_cv_text(frame, "CHANNELING", (int(center[0] - 70), int(center[1] + 155)), 0.55, (240, 255, 255))

    if now < player.frozen_until:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 225, 130), 2, cv2.LINE_AA)
        draw_cv_text(frame, "FROZEN", (x1 + 15, y1 - 10), 0.6, (255, 225, 130), thickness=2)

    if now < player.silenced_until:
        draw_cv_text(frame, "SILENCED", (x1 + 5, y2 + 25), 0.65, (80, 80, 255), thickness=2)


def _draw_cast_rune(frame, wand, now, color, phase):
    """Two counter-rotating arc rings + a bright core at the wand tip."""
    center = (int(wand[0]), int(wand[1]))
    base_r = int(26 + 6 * phase)
    spin = now * 220.0
    bright = tuple(min(255, int(c * 1.2 + 30)) for c in color)
    for k in range(3):
        start = (spin + k * 120) % 360
        cv2.ellipse(frame, center, (base_r, base_r), 0, start, start + 70, bright, 2, cv2.LINE_AA)
    inner_r = int(16 + 4 * phase)
    for k in range(3):
        start = (-spin * 1.4 + k * 120) % 360
        cv2.ellipse(frame, center, (inner_r, inner_r), 0, start, start + 60, color, 1, cv2.LINE_AA)
    cv2.circle(frame, center, max(2, int(4 + 2 * phase)), (255, 255, 255), -1, cv2.LINE_AA)


def draw_shield(frame, player, now):
    if not player.has_shield(now):
        return
    center = player.center()
    shield_x = center[0] + (105 if player.side == "left" else -105)
    shield_center = (int(shield_x), int(center[1] - 15))
    start, end = (-65, 65) if player.side == "left" else (115, 245)
    alpha = 0.35 + 0.12 * math.sin(now * 12)
    overlay = frame.copy()
    cv2.ellipse(
        overlay,
        shield_center,
        (95, 150),
        0,
        start,
        end,
        SPELLS["protego"]["color"],
        18,
        cv2.LINE_AA,
    )
    cv2.ellipse(
        overlay,
        shield_center,
        (70, 120),
        0,
        start,
        end,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    if player.last_message == "SHIELD HIT" and now < player.message_until:
        ripple = int(72 + 38 * max(0.0, 1.0 - (player.message_until - now) / 0.7))
        cv2.ellipse(
            overlay,
            shield_center,
            (ripple, int(ripple * 1.55)),
            0,
            start,
            end,
            (255, 255, 255),
            4,
            cv2.LINE_AA,
        )
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    draw_cv_text(frame, "PROTEGO", (shield_center[0] - 55, shield_center[1] - 150), 0.55, THEME["text"])
