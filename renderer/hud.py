import cv2

from config import HEIGHT, MAX_MANA, SPELLS, THEME, WIDTH
from game.battle_engine import DRAW
from renderer.effects import draw_bar
from renderer.text import draw_centered_text, draw_cv_text, draw_text


def spell_status_text(spell_cd, global_cd, enough_mana):
    if spell_cd > 0:
        return "CD"
    if global_cd > 0:
        return "WAIT"
    if not enough_mana:
        return "MANA"
    return "READY"


def compact_footer_hint():
    return "V input  C lock  D debug  B/N audio  SPACE reset  M menu"


def player_condition_text(silence, global_cd):
    if silence > 0:
        return "SILENCE"
    if global_cd > 0:
        return "RECOVER"
    return ""


def draw_hud(frame, game, now, fps, cv_status="CV OFF", title="SPELLS BATTLE MVP", footer_left=None, footer_right=None, solo_dummy_defeated=None, show_debug=False):
    cv2.line(frame, (WIDTH // 2, 96), (WIDTH // 2, HEIGHT - 86), THEME["panel_border"], 1, cv2.LINE_AA)
    draw_centered_text(frame, title, WIDTH // 2, 34, size=26, color=THEME["text"], face="title")
    if show_debug:
        draw_cv_text(frame, cv_status, (WIDTH // 2 - 150, HEIGHT - 42), 0.47, THEME["debug"])
        draw_cv_text(frame, f"FPS {fps:04.1f}", (WIDTH - 92, HEIGHT - 18), 0.43, THEME["muted"])

    for player in game.players:
        if player.side == "left":
            x = 28
            align_right = False
        else:
            x = WIDTH - 348
            align_right = True
        y = 24
        name_text = f"{player.name} {player.display_name}"
        draw_text(frame, name_text, (x, y + 2), size=22, color=THEME["text"], face="title")
        draw_cv_text(frame, player.profile.buff_label, (x + 148, y + 17), 0.36, THEME["muted"])
        draw_bar(frame, x, y + 28, 320, 22, player.hp, player.max_hp, THEME["hp"], "HP", trail_value=player.max_hp)
        draw_bar(frame, x, y + 55, 320, 18, player.mana, MAX_MANA, THEME["mana"], "MP")
        shield_max = SPELLS["protego"]["shield_value"]
        shield_value = player.shield_value if player.has_shield(now) else 0
        draw_bar(frame, x, y + 78, 320, 14, shield_value, shield_max, THEME["shield"], "SH")

        silence = max(0.0, player.silenced_until - now)
        global_cd = max(0.0, player.global_cooldown_until - now)
        condition = player_condition_text(silence, global_cd)
        if condition:
            draw_cv_text(frame, condition, (x, y + 114), 0.46, THEME["gold_bright"])
        if player.last_spell and player.last_spell != "-":
            draw_cv_text(frame, f"LAST {player.last_spell}", (x + 116, y + 114), 0.43, THEME["muted"])

        sx = x
        sy = y + 130
        for idx, spell_name in enumerate(["incendio", "stupefy", "glacius", "protego", "lumos"]):
            spell = SPELLS[spell_name]
            cd = max(0.0, player.spell_cooldown_until[spell_name] - now)
            enough_mana = player.mana >= spell["mana"]
            ready = cd <= 0 and global_cd <= 0 and enough_mana and now >= player.silenced_until
            color = THEME["ready"] if ready else THEME["blocked"]
            if not enough_mana:
                color = THEME["no_mana"]
            bx = sx + idx * 63
            cv2.rectangle(frame, (bx, sy), (bx + 58, sy + 38), color, -1)
            cv2.rectangle(frame, (bx, sy), (bx + 58, sy + 38), THEME["panel_border"], 1)
            draw_cv_text(frame, spell["label"], (bx + 7, sy + 15), 0.42, THEME["text"])
            text = spell_status_text(cd, global_cd, enough_mana)
            text_scale = 0.34 if len(text) > 4 else 0.39
            draw_cv_text(frame, text, (bx + 6, sy + 31), text_scale, THEME["text"])

            if not ready:
                if cd > 0:
                    progress = 1.0 - min(1.0, cd / max(spell["cooldown"], 0.01))
                elif global_cd > 0:
                    progress = 1.0 - min(1.0, global_cd / 1.0)
                else:
                    progress = 0.0
                if progress > 0:
                    cv2.circle(frame, (bx + 48, sy + 10), 6, THEME["gold_bright"], 1, cv2.LINE_AA)
                    cv2.ellipse(frame, (bx + 48, sy + 10), (6, 6), -90, 0, int(progress * 360), THEME["gold_bright"], 2, cv2.LINE_AA)

        if now < player.message_until:
            msg_x = int(player.center()[0] - 80)
            msg_y = int(player.center()[1] - 190)
            draw_cv_text(frame, player.last_message, (msg_x, msg_y), 0.65, (255, 255, 255), face="title")

    hint = compact_footer_hint()
    if footer_left:
        hint = footer_left
    if footer_right:
        hint = f"{hint}   {footer_right}" if footer_left else footer_right
    if len(hint) > 92:
        hint = compact_footer_hint()
    if show_debug:
        draw_cv_text(frame, hint, (26, HEIGHT - 18), 0.46, THEME["muted"])

    if game.winner is not None and solo_dummy_defeated is None:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), THEME["bg"], -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        text = "DRAW" if game.winner == DRAW else f"{game.players[game.winner].display_name} WINS"
        draw_centered_text(frame, text, WIDTH // 2, HEIGHT // 2, size=52, color=THEME["text"], face="title")
        draw_centered_text(frame, "Press SPACE to restart", WIDTH // 2, HEIGHT // 2 + 50, size=24, color=THEME["muted"])
    elif solo_dummy_defeated:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), THEME["bg"], -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        draw_centered_text(frame, "DUMMY DEFEATED", WIDTH // 2, HEIGHT // 2, size=52, color=THEME["text"], face="title")
        draw_centered_text(frame, "Press SPACE to reset", WIDTH // 2, HEIGHT // 2 + 50, size=24, color=THEME["muted"])
