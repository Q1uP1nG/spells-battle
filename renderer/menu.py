import math

import cv2
import numpy as np

from config import HEIGHT, THEME, WIDTH
from game.cv_training import get_training_label
from renderer.character_assets import draw_character_sprite
from renderer.effects import draw_glow_circle
from renderer.text import draw_centered_text, draw_cv_text, draw_text


MENU_OPTIONS = [
    ("1", "SOLO SHOWCASE", "Practice spells, CV input, and keyboard casting."),
    ("2", "DUEL BATTLE", "Two players, projectiles, shields, and cooldowns."),
    ("3", "PVE BATTLE", "Play PVE Battle with the full ruleset."),
    ("4", "CV BANK", "Browse, replace, and maintain gesture bank slots."),
    ("5", "REMOTE DUEL", "Create or join a room for two-device online battle."),
]

INTRO_SPELL_SHAPES = [
    ("INC", "Push toward opponent."),
    ("STU", "Draw a circle."),
    ("GLA", "Slash downward."),
    ("PRO", "Open palm shield."),
    ("LUM", "Flick upward."),
    ("OVR", "Draw zigzag overload."),
]

INTRO_MODE_ROWS = [
    ("1", "Solo training dummy."),
    ("2", "Duel battle."),
    ("3", "PVE Battle."),
    ("4", "CV bank maintenance."),
    ("5", "Remote room-code duel."),
]


def solo_overlay_label(mode):
    return "PVE Battle" if mode == "pve" else "Training Dummy"


def draw_intro(frame, cv_status, fps, tick):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), THEME["bg"], -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)

    pulse = 0.5 + 0.5 * math.sin(tick * 0.045)
    center = np.array([WIDTH // 2, 150], dtype=np.float32)
    draw_glow_circle(frame, center, 145 + 20 * pulse, THEME["gold"], 0.16, 6)
    draw_centered_text(frame, "SPELLS", WIDTH // 2, 110, size=64, color=THEME["text"], face="title")
    draw_centered_text(frame, "Vision-based magic casting", WIDTH // 2, 168, size=24, color=THEME["muted"])

    left_x = 90
    panel_w = 520
    gap_x = 60
    right_x = left_x + panel_w + gap_x
    top_y = 218
    gap_y = 24
    how_rows = [
        ("Finger", "Point and draw the spell trail."),
        ("Wand", "Press V, lock a bright tip with C."),
        ("Shield", "Open palm and hold for Protego."),
        ("Keyboard", "P1 Q/W/E/R/T, P2 U/I/O/P/L."),
    ]
    tips_rows = [
        ("D", "Toggle detailed CV debug."),
        ("B/N", "BGM and mute."),
        ("M", "Return to menu."),
        ("X", "Quit."),
    ]
    top_h = max(rule_panel_height(len(how_rows)), rule_panel_height(len(INTRO_SPELL_SHAPES)))
    bottom_y = top_y + top_h + gap_y
    bottom_h = max(rule_panel_height(len(INTRO_MODE_ROWS)), rule_panel_height(len(tips_rows)))

    draw_rule_panel(frame, left_x, top_y, panel_w, top_h, "HOW TO CAST", how_rows)
    draw_rule_panel(frame, right_x, top_y, panel_w, top_h, "SPELL SHAPES", INTRO_SPELL_SHAPES)
    draw_rule_panel(frame, left_x, bottom_y, panel_w, bottom_h, "MODES", INTRO_MODE_ROWS)
    draw_rule_panel(frame, right_x, bottom_y, panel_w, bottom_h, "TIPS", tips_rows)

    if int(tick / 24) % 2 == 0:
        draw_centered_text(frame, "PRESS ANY KEY TO OPEN MENU", WIDTH // 2, HEIGHT - 58, size=26, color=THEME["gold_bright"], face="title")


def rule_panel_height(row_count):
    return 62 + max(0, int(row_count) - 1) * 26 + 31


def draw_rule_panel(frame, x, y, w, h, title, rows):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), THEME["panel"], -1)
    cv2.addWeighted(overlay, 0.80, frame, 0.20, 0, frame)
    cv2.rectangle(frame, (x, y), (x + w, y + h), THEME["panel_border"], 1, cv2.LINE_AA)
    draw_text(frame, title, (x + 18, y + 10), size=22, color=THEME["text"], face="title")
    label_w = max((rule_label_width(key) for key, _text in rows), default=48)
    for idx, (key, text) in enumerate(rows):
        yy = y + 62 + idx * 26
        key_scale = fit_text_scale(key, cv2.FONT_HERSHEY_SIMPLEX, label_w - 10, 0.46, 1, 0.34)
        cv2.rectangle(frame, (x + 18, yy - 16), (x + 18 + label_w, yy + 5), THEME["gold"], -1)
        draw_cv_text(frame, key, (x + 27, yy), key_scale, THEME["text"])
        draw_cv_text(frame, text, (x + 34 + label_w, yy), 0.47, THEME["muted"])


def rule_label_width(key):
    return 74 if len(key) > 4 else 48


def draw_menu(frame, cv_status, fps, tick, game=None):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), THEME["bg"], -1)
    cv2.addWeighted(overlay, 0.66, frame, 0.34, 0, frame)

    pulse = 0.5 + 0.5 * math.sin(tick * 0.04)
    center = np.array([WIDTH // 2, 132], dtype=np.float32)
    draw_glow_circle(frame, center, 105 + 16 * pulse, THEME["gold"], 0.15, 5)
    draw_centered_text(frame, "SPELLS", WIDTH // 2, 108, size=56, color=THEME["text"], face="title")
    draw_centered_text(frame, "Choose a mode", WIDTH // 2, 158, size=23, color=THEME["muted"])

    start_y = 196
    for idx, (key, title, subtitle) in enumerate(MENU_OPTIONS):
        draw_menu_option(frame, 300, start_y + idx * 76, key, title, subtitle)

    draw_cv_text(frame, "ESC/X quit", (36, HEIGHT - 32), 0.56, THEME["muted"])


def draw_menu_option(frame, x, y, key, title, subtitle):
    card_width = 680
    card_height = 66
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + card_width, y + card_height), THEME["panel"], -1)
    cv2.addWeighted(overlay, 0.88, frame, 0.12, 0, frame)
    cv2.rectangle(frame, (x, y), (x + card_width, y + card_height), THEME["panel_border"], 1, cv2.LINE_AA)
    cv2.rectangle(frame, (x + 18, y + 15), (x + 62, y + 51), THEME["gold"], -1)
    draw_cv_text(frame, key, (x + 34, y + 40), 0.74, (255, 255, 255), face="title")
    draw_text(frame, title, (x + 86, y + 9), size=25, color=THEME["text"], face="title")
    subtitle_x = x + 86
    subtitle_width = card_width - 108
    subtitle_scale = fit_text_scale(subtitle, cv2.FONT_HERSHEY_SIMPLEX, subtitle_width, 0.48, 1)
    draw_cv_text(frame, subtitle, (subtitle_x, y + 52), subtitle_scale, THEME["muted"])


def draw_remote_lobby(frame, session, room_code_input="", joining=False):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), THEME["bg"], -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    draw_centered_text(frame, "REMOTE DUEL", WIDTH // 2, 104, size=48, color=THEME["text"], face="title")
    draw_centered_text(frame, session.status_message, WIDTH // 2, 156, size=23, color=THEME["gold_bright"])
    x, y, w, h = 260, 205, 760, 360
    cv2.rectangle(frame, (x, y), (x + w, y + h), THEME["panel"], -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), THEME["panel_border"], 1, cv2.LINE_AA)
    draw_centered_text(frame, f"ROOM  {session.room_code or '------'}", WIDTH // 2, y + 70, size=35, color=THEME["text"], face="title")
    if session.player_index is None:
        draw_centered_text(frame, "C  CREATE ROOM", WIDTH // 2, y + 135, size=25, color=THEME["muted"])
        draw_centered_text(frame, "J  JOIN ROOM", WIDTH // 2, y + 180, size=25, color=THEME["muted"])
    else:
        player = session.game.players[session.player_index]
        draw_centered_text(frame, f"YOU ARE P{session.player_index + 1}  ·  {player.display_name}", WIDTH // 2, y + 145, size=25, color=THEME["muted"])
        draw_centered_text(frame, "A / F CHARACTER     R READY", WIDTH // 2, y + 205, size=23, color=THEME["text"])
    if joining:
        draw_centered_text(frame, f"TYPE ROOM CODE: {room_code_input or '_'}", WIDTH // 2, y + 255, size=26, color=THEME["gold_bright"])
        draw_centered_text(frame, "ENTER JOIN  ·  BACKSPACE EDIT", WIDTH // 2, y + 295, size=18, color=THEME["muted"])
    elif session.last_error:
        draw_centered_text(frame, session.last_error[:70], WIDTH // 2, y + 270, size=19, color=(100, 120, 255))
    draw_centered_text(frame, "M / ESC  BACK TO MENU", WIDTH // 2, y + 330, size=18, color=THEME["muted"])


def draw_character_select(frame, game, fps, tick, mode_label=""):
    if game is None or not hasattr(game, "players"):
        return

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), (8, 9, 16), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    pulse = 0.5 + 0.5 * math.sin(tick * 0.05)

    title = "SELECT CHARACTERS"
    if mode_label:
        title = f"{title} - {mode_label}"
    draw_cv_text(frame, title, (WIDTH // 2 - 260, 96), 1.1, (248, 248, 255), face="title", thickness=2)

    card_w, card_h = 380, 460
    gap = 80
    total_w = 2 * card_w + gap
    start_x = (WIDTH - total_w) // 2
    y = 150

    is_pve = mode_label == "PVE BATTLE"
    rows = [
        ("P1", "A / F", game.players[0]),
        ("P2", "AI" if is_pve else "J / K", game.players[1]),
    ]

    for idx, (label, keys, player) in enumerate(rows):
        x = start_x + idx * (card_w + gap)
        profile = player.profile

        card_overlay = frame.copy()
        cv2.rectangle(card_overlay, (x, y), (x + card_w, y + card_h), (20, 23, 33), -1)
        cv2.addWeighted(card_overlay, 0.90, frame, 0.10, 0, frame)
        cv2.rectangle(frame, (x, y), (x + card_w, y + card_h), profile.color, 2, cv2.LINE_AA)

        draw_cv_text(frame, label, (x + 30, y + 52), 0.9, (245, 245, 255), face="title", thickness=2)
        draw_cv_text(frame, keys, (x + card_w - 110, y + 52), 0.6, (170, 185, 205))

        avatar_y = y + 160
        draw_glow_circle(frame, np.array([x + card_w // 2, avatar_y], dtype=np.float32), 90, profile.color, 0.18, 8)
        asset_drawn = draw_character_sprite(
            frame,
            character_id=profile.id,
            pose="normal",
            bottom_center=(x + card_w // 2, y + 284),
            max_height=220,
            max_width=250,
        )
        if not asset_drawn:
            cv2.circle(frame, (x + card_w // 2, avatar_y), 70, profile.color, -1, cv2.LINE_AA)
            cv2.circle(frame, (x + card_w // 2, avatar_y), 70, (255, 255, 255), 2, cv2.LINE_AA)

        name = profile.name
        (name_w, _), _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_DUPLEX, 1.3, 2)
        draw_cv_text(frame, name, (x + (card_w - name_w) // 2, y + 300), 1.3, (245, 245, 255), face="title", thickness=2)

        buff = profile.buff_label
        buff_scale = fit_text_scale(buff, cv2.FONT_HERSHEY_SIMPLEX, card_w - 60, 0.6, 1, 0.42)
        (buff_w, _), _ = cv2.getTextSize(buff, cv2.FONT_HERSHEY_SIMPLEX, buff_scale, 1)
        draw_cv_text(frame, buff, (x + (card_w - buff_w) // 2, y + 350), buff_scale, (200, 215, 232))

        pose = profile.poses.get("normal", "READY")
        draw_cv_text(frame, f"POSE: {pose}", (x + 30, y + 405), 0.5, (160, 175, 195))

    hint = "PRESS SPACE OR ENTER TO START"
    alpha = 0.7 + 0.3 * pulse
    color = (int(90 + 60 * alpha), int(220 + 20 * alpha), int(255))
    (hint_w, _), _ = cv2.getTextSize(hint, cv2.FONT_HERSHEY_DUPLEX, 0.8, 1)
    draw_cv_text(frame, hint, (WIDTH // 2 - hint_w // 2, HEIGHT - 90), 0.8, color, face="title")



def fit_text_scale(text, font_face, max_width, preferred_scale, thickness, min_scale=0.42):
    width = cv2.getTextSize(text, font_face, preferred_scale, thickness)[0][0]
    if width <= max_width:
        return preferred_scale
    fitted = preferred_scale * max_width / max(width, 1)
    return max(min_scale, round(fitted, 3))


def draw_solo_overlay(frame, game, now, cv_status, mode="solo"):
    label = solo_overlay_label(mode)
    cx, cy = game.players[1].center()
    draw_cv_text(frame, label, (int(cx - 78), int(cy + 155)), 0.50, (205, 212, 225))
    if game.solo_dummy_defeated:
        draw_cv_text(frame, "DEFEATED", (int(cx - 55), int(cy + 185)), 0.65, (255, 80, 80), face="title", thickness=2)


def draw_pve_pause_overlay(frame, runner, cv_status):
    title = "PVE READY" if not runner.pve_has_started else "PVE PAUSED"
    subtitle = "Set input mode and lock wand color before battle."
    action = "SPACE START" if not runner.pve_has_started else "SPACE RESUME"
    x = WIDTH // 2 - 270
    y = HEIGHT // 2 - 90
    w = 540
    h = 170
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), (12, 14, 22), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (105, 135, 170), 1, cv2.LINE_AA)
    draw_cv_text(frame, title, (x + 24, y + 42), 0.86, (245, 245, 255), face="title")
    draw_cv_text(frame, subtitle, (x + 24, y + 74), 0.50, (220, 230, 240))
    draw_cv_text(frame, "V input mode   C lock wand color   D debug", (x + 24, y + 105), 0.50, (180, 215, 235))
    draw_cv_text(frame, f"{action}   Backspace restart   ESC menu", (x + 24, y + 136), 0.52, (110, 235, 255))
    status = cv_status if len(cv_status) <= 62 else cv_status[:59] + "..."
    draw_cv_text(frame, status, (x + 24, y + 158), 0.40, (190, 205, 220))


def draw_training_overlay(frame, session):
    x = 28
    y = 250
    w = 520
    h = 210
    cv2.rectangle(frame, (x, y), (x + w, y + h), (18, 20, 28), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (105, 135, 170), 1)

    target = get_training_label(session.current_target_spell)
    draw_cv_text(frame, "CV Bank", (x + 14, y + 30), 0.72, (245, 245, 255), face="title")
    draw_cv_text(
        frame,
        f"Target: {target['label']}   Slot {session.current_attempt_number}/{session.attempts_per_spell}   {session.current_slot_status}",
        (x + 14, y + 60),
        0.50,
        (220, 235, 245),
    )
    draw_template_preview(
        frame,
        session.current_display_points(),
        x + w - 166,
        y + 20,
        146,
        146,
        (110, 235, 255) if session.current_slot_status == "DEFAULT" else (245, 198, 108),
    )

    if session.has_pending_review:
        label = get_training_label(session.pending_label)
        primary = session.pending_event.get("primary", {}) if session.pending_event else {}
        primary_text = primary.get("spell") or "-"
        draw_cv_text(frame, "Review frozen trail", (x + 14, y + 92), 0.52, (110, 235, 255))
        draw_cv_text(frame, f"Label: {label['label']}   Pred={primary_text}", (x + 14, y + 120), 0.48, (230, 232, 238))
        draw_cv_text(frame, "Enter save   Backspace rerecord   4/5/6/7/8 relabel", (x + 14, y + 150), 0.46, (210, 220, 235))
    elif session.is_complete:
        draw_cv_text(frame, "Template bank full. Use A/D or [/ ] to browse.", (x + 14, y + 100), 0.48, (110, 235, 255))
        draw_cv_text(frame, "Backspace clears current slot for rerecord.", (x + 14, y + 130), 0.47, (210, 220, 235))
    else:
        draw_cv_text(frame, "Draw the target gesture, then stop moving.", (x + 14, y + 100), 0.50, (230, 232, 238))
        draw_cv_text(frame, "A/D spell   [/ ] slot   Backspace rerecord.", (x + 14, y + 130), 0.47, (210, 220, 235))


def draw_template_preview(frame, points, x, y, w, h, color):
    cv2.rectangle(frame, (x, y), (x + w, y + h), (54, 64, 82), 1)
    draw_cv_text(frame, "start", (x + 8, y + h + 18), 0.32, (120, 220, 140))
    draw_cv_text(frame, "end", (x + w - 42, y + h + 18), 0.32, (245, 130, 118))
    pts = np.asarray(points or [], dtype=np.float32)
    if pts.ndim != 2 or pts.shape[0] < 2 or pts.shape[1] < 2:
        draw_cv_text(frame, "EMPTY", (x + 18, y + h // 2), 0.36, (155, 166, 184))
        return

    pts = pts[:, :2]
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    pad = 12
    inner_w = max(1, w - 2 * pad)
    inner_h = max(1, h - 2 * pad)
    span = mx - mn
    max_span = max(float(span[0]), float(span[1]), 1e-3)
    scale = min(inner_w, inner_h) / max_span
    center = (mn + mx) * 0.5
    box_center = np.array([x + w * 0.5, y + h * 0.5], dtype=np.float32)
    draw_pts = np.column_stack((
        box_center[0] + (pts[:, 0] - center[0]) * scale,
        box_center[1] + (pts[:, 1] - center[1]) * scale,
    )).astype(np.int32)
    cv2.polylines(frame, [draw_pts], False, color, 2, cv2.LINE_AA)
    if len(draw_pts) >= 2:
        cv2.arrowedLine(frame, tuple(draw_pts[-2]), tuple(draw_pts[-1]), color, 2, cv2.LINE_AA, tipLength=0.35)
    cv2.circle(frame, tuple(draw_pts[0]), 3, (120, 220, 140), -1, cv2.LINE_AA)
    cv2.circle(frame, tuple(draw_pts[-1]), 4, (245, 130, 118), -1, cv2.LINE_AA)


