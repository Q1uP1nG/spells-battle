import time

import cv2
import numpy as np

from config import FPS_FALLBACK, HEIGHT, P1_KEYS, P2_KEYS, WIDTH
from cv.controller import CVGestureController
from game.audio import AudioManager
from game.battle import BattleGame
from game.cv_training import get_training_label
from game.mode import GameMode, ModeRunner
from game.remote_session import RemoteBattleSession, RemoteSessionState
from game.room_code_input import PhysicalRoomCodeKeyboard, apply_room_code_key
from game.session import LocalBattleSession
from game.settings import collect, load, restore, save
from renderer.hud import draw_hud
from renderer.text import draw_cv_text
from renderer.menu import (
    draw_character_select,
    draw_intro,
    draw_menu,
    draw_pve_pause_overlay,
    draw_remote_lobby,
    draw_solo_overlay,
    draw_training_overlay,
)
from renderer.player import draw_player, draw_shield
from renderer.effects import apply_screen_feedback, draw_flash_messages, draw_shockwaves
from renderer.postfx import PostFX
from renderer.projectile import draw_particles, draw_projectile


def prepare_frame(cap, tick):
    ret, frame = cap.read() if cap is not None else (False, None)
    if ret:
        frame = cv2.flip(frame, 1)
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
    else:
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        x = np.linspace(0, 1, WIDTH, dtype=np.float32)
        y = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None]
        frame[:, :, 0] = (24 + 18 * y).astype(np.uint8)
        frame[:, :, 1] = (18 + 24 * x).astype(np.uint8)
        frame[:, :, 2] = (28 + 12 * np.sin(tick * 0.03)).astype(np.uint8)

    dark = np.zeros_like(frame)
    dark[:, :, :] = (18, 16, 24)
    frame = cv2.addWeighted(frame, 0.62, dark, 0.38, 0)
    return frame


def print_controls():
    print("Spells")
    print("Menu: 1 Solo | 2 Duel | 3 PVE | 4 CV Bank | 5 Remote Duel | M Menu")
    print("Character Select: P1 A/F | P2 J/K   SPACE/ENTER confirm")
    print("P1: Q Incendio | W Stupefy | E Glacius | R Protego | T Lumos")
    print("P2: U Incendio | I Stupefy | O Glacius | P Protego | L Lumos")
    print("CV: MediaPipe Hands auto-enable. V cycles finger / colored wand-tip tracking.")
    print("Wand mode: put a bright yellow/green/cyan/pink marker on the tip, center it, then press C to lock its color.")
    print("CV Bank: Enter save | Backspace rerecord | A/D spell | [/ ] slot | 4/5/6/7/8 relabel")
    print("PVE: SPACE start/pause/resume | Backspace restart | ESC back to menu")
    print("Solo/Duel: SPACE reset | B toggle BGM | N toggle SFX mute | X quit")
    print("Remote: 5 then C create or J join; A/F character; R ready")


# ---------------------------------------------------------------------------
# Mode → runner dispatch
# ---------------------------------------------------------------------------

MODES_BY_KEY = {
    ord("1"): GameMode.SOLO,
    ord("2"): GameMode.DUEL,
    ord("3"): GameMode.PVE,
    ord("4"): GameMode.CV_TRAINING,
    ord("5"): GameMode.REMOTE_LOBBY,
}


def format_cv_training_status(cv_status, session):
    target = get_training_label(session.current_target_spell)["label"]
    cv_status = f"{cv_status} | TARGET {target} {session.current_attempt_number}/{session.attempts_per_spell}"
    if session.has_pending_review:
        label = get_training_label(session.pending_label)["label"]
        cv_status = f"{cv_status} | REVIEW {label}"
    return cv_status

SELECT_KEYS = {
    ord("a"): (0, -1),
    ord("A"): (0, -1),
    ord("f"): (0, 1),
    ord("F"): (0, 1),
    ord("j"): (1, -1),
    ord("J"): (1, -1),
    ord("k"): (1, 1),
    ord("K"): (1, 1),
}

CONFIRM_KEYS = {ord(" "), 13, 10}  # space, enter/return
QUIT_KEYS = {ord("x"), ord("X")}
RESTART_KEYS = {8, 127}


def should_leave_intro(key):
    return key not in (255, 27)


def should_quit(key, mode):
    return key in QUIT_KEYS or (key == 27 and mode == GameMode.MENU)


def should_return_to_menu(key, mode):
    return key == 27 and mode != GameMode.MENU


def should_toggle_debug(key, mode):
    return key in (ord("d"), ord("D")) and mode != GameMode.CV_TRAINING


def should_reset_with_space(key, mode):
    return key == ord(" ") and mode not in (
        GameMode.PVE,
        GameMode.CV_TRAINING,
        GameMode.REMOTE_LOBBY,
        GameMode.REMOTE_DUEL,
    )


def should_enter_remote_duel(session):
    """Keep room reconnects in the lobby until a round has actually started."""
    return bool(
        session is not None
        and session.has_room_assignment
        and (
            session.state in (RemoteSessionState.RUNNING, RemoteSessionState.ROUND_OVER)
            or (session.state == RemoteSessionState.RECONNECTING and session.round_started)
        )
    )


def handle_cv_training_key(key, runner, cv_controller):
    if runner.mode == GameMode.CV_TRAINING:
        return runner.handle_training_key(key, cv_controller)
    return ""


def handle_character_key(key, game):
    if key not in SELECT_KEYS:
        return ""
    player_index, direction = SELECT_KEYS[key]
    profile = game.cycle_player_character(player_index, direction)
    return f"P{player_index + 1}: {profile.name} - {profile.buff_label}"


def handle_battle_cast_key(key, runner, battle_session, now):
    """Route every player keyboard cast through the active battle session."""
    if key in P1_KEYS:
        player_index = getattr(battle_session, "player_index", None)
        if player_index is None:
            player_index = 0
        return battle_session.request_cast(
            player_index=player_index,
            spell=P1_KEYS[key],
            now=now,
            source="keyboard",
        )
    if runner.accepts_p2_keyboard and key in P2_KEYS:
        return battle_session.request_cast(
            player_index=1,
            spell=P2_KEYS[key],
            now=now,
            source="keyboard",
        )
    return None


def play_sound_event(audio, event):
    kind = event[0]
    if kind == "cast":
        audio.play_cast(event[1])
    elif kind == "hit":
        audio.play_hit()
    elif kind == "shield_hit":
        audio.play_shield_hit()
    elif kind == "round_over":
        audio.play_round_over()
    elif kind == "heal_complete":
        audio.play_cast("lumos")
    elif kind == "cast_fail":
        audio.play_cast_fail()
    elif kind == "clash":
        audio.play_effect(event[1])


def switch_mode(mode, game, cv_controller):
    """Return a fresh runner entered into the given mode."""
    runner = ModeRunner(mode)
    runner.enter(game, cv_controller)
    return runner


def main():
    print_controls()
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    else:
        cap.release()
        cap = None
        print("Camera not available; using generated arena background.")

    local_game = BattleGame()
    local_battle_session = LocalBattleSession(local_game)
    game = local_game
    battle_session = local_battle_session
    remote_session = None
    joining_remote_room = False
    remote_room_input = ""
    room_code_keyboard = PhysicalRoomCodeKeyboard()
    postfx = PostFX()
    cv_controller = CVGestureController(battle_session=battle_session)
    audio = AudioManager()
    audio_available = audio.init()
    if audio_available:
        print("Audio: enabled (B=bgm, N=mute)")
    else:
        print("Audio: unavailable (pygame mixer not found)")

    saved = load()
    restore(cv_controller, saved, game)
    print(cv_controller.detail_status)
    runner = ModeRunner(GameMode.MENU)
    show_intro = True
    last = time.monotonic()
    fps = FPS_FALLBACK
    tick = 0
    cv_mode_notice = ""
    cv_mode_notice_until = 0.0

    while True:
        now = time.monotonic()
        dt = min(0.05, now - last)
        last = now
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1

        frame = prepare_frame(cap, tick)
        calibration_frame = frame.copy()
        tick += 1

        # --- render -------------------------------------------------------
        if remote_session is not None:
            remote_session.update(now, dt)
            if runner.mode == GameMode.REMOTE_DUEL and not remote_session.has_room_assignment:
                runner = ModeRunner(GameMode.REMOTE_LOBBY)
            if runner.mode == GameMode.REMOTE_LOBBY and should_enter_remote_duel(
                remote_session
            ):
                runner = ModeRunner(GameMode.REMOTE_DUEL)

        if show_intro:
            draw_intro(frame, cv_controller.status, fps, tick)
        elif runner.mode == GameMode.MENU:
            draw_menu(frame, cv_controller.status, fps, tick, game)
        elif runner.mode == GameMode.CHARACTER_SELECT:
            draw_character_select(frame, game, fps, tick, mode_label=runner.pending_mode.value.upper() if runner.pending_mode else "")
        elif runner.mode == GameMode.REMOTE_LOBBY:
            draw_remote_lobby(
                frame,
                remote_session,
                room_code_input=remote_room_input,
                joining=joining_remote_room,
            )
        else:
            if runner.mode == GameMode.REMOTE_DUEL:
                cv_controller.update(
                    frame,
                    game,
                    now,
                    force_player_index=remote_session.player_index or 0,
                    allow_casting=remote_session.state == RemoteSessionState.RUNNING,
                )
            else:
                runner.update(frame, game, cv_controller, now, dt)
            for player in game.players:
                draw_player(frame, player, now, winner=game.winner)
            for player in game.players:
                draw_shield(frame, player, now)
            spell_base = postfx.snapshot(frame)
            for proj in game.projectiles:
                draw_projectile(frame, proj, now)
            draw_particles(frame, game.particles)
            draw_shockwaves(frame, game, now)
            postfx.render(frame, spell_base)
            draw_flash_messages(frame, game, now)
            cv_controller.draw(frame, now, show_debug=cv_controller.verbose_debug)

            cv_status = cv_controller.status
            if runner.mode == GameMode.REMOTE_DUEL:
                latency = "--" if remote_session.rtt_ms is None else f"{remote_session.rtt_ms:.0f}ms"
                cv_status = f"{cv_status} | NET {remote_session.state.value} {latency}"
            if runner.mode == GameMode.PVE and runner.pve_paused:
                state = "READY" if not runner.pve_has_started else "PAUSED"
                cv_status = f"{cv_status} | {state}"
            if runner.mode == GameMode.CV_TRAINING and runner.training_session is not None:
                cv_status = format_cv_training_status(cv_status, runner.training_session)

            draw_hud(
                frame,
                game,
                now,
                fps,
                cv_status,
                title=runner.title,
                footer_left=runner.footer_left or "P1 Q/W/E/R/T = INC/STU/GLA/PRO/LUM   V CV mode   C lock colored wand",
                footer_right=runner.footer_right or "SPACE reset   M menu   X quit",
                solo_dummy_defeated=runner.solo_dummy_defeated_for_hud(game),
                show_debug=cv_controller.verbose_debug,
            )
            if runner.show_solo_overlay:
                draw_solo_overlay(frame, game, now, cv_controller.status, mode=runner.mode.value)
            if runner.mode == GameMode.PVE and runner.pve_paused:
                draw_pve_pause_overlay(frame, runner, cv_status)
            if runner.mode == GameMode.CV_TRAINING and runner.training_session is not None:
                draw_training_overlay(frame, runner.training_session)

            if audio_available:
                if game.sound_events:
                    for event in game.sound_events:
                        play_sound_event(audio, event)
                    game.sound_events.clear()

        if now < cv_mode_notice_until:
            draw_cv_text(frame, cv_mode_notice, (WIDTH // 2 - 150, HEIGHT // 2 + 210), 0.8, (90, 245, 255), face="title")

        if not show_intro and runner.mode not in (GameMode.MENU, GameMode.CHARACTER_SELECT):
            apply_screen_feedback(frame, game, now)

        # --- input --------------------------------------------------------
        cv2.imshow("Spells Battle MVP", frame)
        key = cv2.waitKey(1) & 0xFF

        # Room-code entry owns the keyboard.  Route it before every global
        # hotkey so B/N/M/V/X/D remain valid code characters.  On Windows the
        # physical-key poller also bypasses Chinese-IME VK_PROCESSKEY (229).
        if runner.mode == GameMode.REMOTE_LOBBY and joining_remote_room:
            room_keys = room_code_keyboard.poll() if room_code_keyboard.available else [key]
            for room_key in room_keys:
                remote_room_input, action = apply_room_code_key(remote_room_input, room_key)
                if action == "cancel":
                    joining_remote_room = False
                    break
                if action == "incomplete":
                    cv_mode_notice = "ROOM CODE NEEDS 6 CHARACTERS"
                    cv_mode_notice_until = now + 1.2
                    break
                if action == "submit":
                    remote_session.join_room(remote_room_input)
                    joining_remote_room = False
                    break
            continue

        if key in QUIT_KEYS:
            break

        if show_intro:
            if should_leave_intro(key):
                show_intro = False
            continue

        if should_quit(key, runner.mode):
            break

        if should_return_to_menu(key, runner.mode):
            if hasattr(cv_controller, "end_training_capture"):
                cv_controller.end_training_capture()
            runner = ModeRunner(GameMode.MENU)
            if remote_session is not None:
                remote_session.close()
                remote_session = None
                game = local_game
                battle_session = local_battle_session
                cv_controller.battle_session = local_battle_session
            game.reset()
            postfx.reset()
            cv_mode_notice = "MENU"
            cv_mode_notice_until = now + 0.8
            continue

        if key == ord("m"):                             # M -> menu
            if hasattr(cv_controller, "end_training_capture"):
                cv_controller.end_training_capture()
            runner = ModeRunner(GameMode.MENU)
            if remote_session is not None:
                remote_session.close()
                remote_session = None
                game = local_game
                battle_session = local_battle_session
                cv_controller.battle_session = local_battle_session
            game.reset()
            postfx.reset()
            continue

        if key in (ord("v"), ord("V")):                 # toggle CV mode
            input_mode = cv_controller.toggle_input_mode()
            save(collect(cv_controller, game))
            cv_mode_notice = f"CV MODE: {input_mode.upper()}"
            cv_mode_notice_until = now + 1.0
            print(cv_mode_notice)
            continue

        if should_toggle_debug(key, runner.mode):
            cv_controller.verbose_debug = not cv_controller.verbose_debug
            cv_mode_notice = f"CV DEBUG: {'VERBOSE' if cv_controller.verbose_debug else 'COMPACT'}"
            cv_mode_notice_until = now + 1.0
            continue

        training_notice = handle_cv_training_key(key, runner, cv_controller)
        if training_notice:
            cv_mode_notice = training_notice
            cv_mode_notice_until = now + 1.2
            print(training_notice)
            continue

        if key in (ord("b"), ord("B")) and audio_available:
            if audio.bgm_playing:
                audio.stop_bgm()
                cv_mode_notice = "BGM OFF"
            else:
                audio.start_bgm()
                cv_mode_notice = "BGM ON"
            cv_mode_notice_until = now + 1.0
            continue

        if key in (ord("n"), ord("N")) and audio_available:
            muted = audio.toggle_mute()
            if muted:
                cv_mode_notice = "AUDIO MUTED"
            else:
                cv_mode_notice = "AUDIO UNMUTED"
                audio.start_bgm()
            cv_mode_notice_until = now + 1.0
            continue
        if (
            key in (ord("c"), ord("C"))
            and cv_controller.input_mode == "wand"
            and runner.mode != GameMode.REMOTE_LOBBY
        ):
            player_index = 0 if key == ord("c") else 1
            ok, message = cv_controller.calibrate_wand_color(calibration_frame, player_index=player_index)
            if ok:
                save(collect(cv_controller, game))
            cv_mode_notice = message
            cv_mode_notice_until = now + 1.4
            print(message)
            continue

        # --- mode-switch keys (only from menu) ---------------------------
        if runner.mode == GameMode.MENU:
            if key in MODES_BY_KEY:
                selected_mode = MODES_BY_KEY[key]
                if audio_available:
                    audio.play_menu_select()
                    if not audio.bgm_playing:
                        audio.start_bgm()
                if selected_mode == GameMode.REMOTE_LOBBY:
                    remote_session = RemoteBattleSession()
                    remote_session.start()
                    game = remote_session.game
                    battle_session = remote_session
                    cv_controller.battle_session = remote_session
                    runner = ModeRunner(GameMode.REMOTE_LOBBY)
                    joining_remote_room = False
                    remote_room_input = ""
                elif selected_mode in (GameMode.DUEL, GameMode.PVE):
                    runner = ModeRunner(GameMode.CHARACTER_SELECT)
                    runner.pending_mode = selected_mode
                    runner.enter(game, cv_controller)
                else:
                    runner = switch_mode(selected_mode, game, cv_controller)
            continue

        if runner.mode == GameMode.REMOTE_LOBBY:
            if key in (ord("c"), ord("C")) and remote_session.player_index is None:
                remote_session.create_room()
                continue
            if key in (ord("j"), ord("J")) and remote_session.player_index is None:
                joining_remote_room = True
                remote_room_input = ""
                room_code_keyboard.begin()
                continue
            if remote_session.player_index is not None and key in (
                ord("a"), ord("A"), ord("f"), ord("F")
            ):
                direction = -1 if key in (ord("a"), ord("A")) else 1
                index = remote_session.player_index
                profile = game.cycle_player_character(index, direction)
                remote_session.select_character(profile.id)
                continue
            if remote_session.player_index is not None and key in (ord("r"), ord("R")):
                remote_session.set_ready(True)
                continue
            continue

        if runner.mode == GameMode.CHARACTER_SELECT:
            if key in SELECT_KEYS:
                player_index, direction = SELECT_KEYS[key]
                if runner.pending_mode == GameMode.PVE and player_index == 1:
                    continue
                profile = game.cycle_player_character(player_index, direction)
                save(collect(cv_controller, game))
                cv_mode_notice = f"P{player_index + 1}: {profile.name} - {profile.buff_label}"
                cv_mode_notice_until = now + 1.2
                print(cv_mode_notice)
                continue
            if key in CONFIRM_KEYS:
                if runner.pending_mode in (GameMode.DUEL, GameMode.PVE):
                    runner = switch_mode(runner.pending_mode, game, cv_controller)
                continue
            continue

        # --- in-game keys ------------------------------------------------
        if runner.mode == GameMode.PVE and key == ord(" "):
            cv_mode_notice = runner.toggle_pve_pause()
            cv_mode_notice_until = now + 1.0
            print(cv_mode_notice)
            continue

        if runner.mode == GameMode.PVE and key in RESTART_KEYS:
            runner.reset(game)
            cv_mode_notice = "PVE READY"
            cv_mode_notice_until = now + 1.0
            print(cv_mode_notice)
            continue

        if runner.mode == GameMode.CV_TRAINING:
            continue

        if (
            runner.mode == GameMode.REMOTE_DUEL
            and key == ord(" ")
            and remote_session.state == RemoteSessionState.ROUND_OVER
        ):
            remote_session.request_rematch()
            continue

        if should_reset_with_space(key, runner.mode):   # SPACE reset outside PVE/training
            runner.reset(game)
            continue

        if runner.mode == GameMode.PVE and runner.pve_paused:
            continue

        handle_battle_cast_key(key, runner, battle_session, now)

    if cap is not None:
        cap.release()
    if remote_session is not None:
        remote_session.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
