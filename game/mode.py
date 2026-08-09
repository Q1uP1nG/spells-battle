from __future__ import annotations

from enum import Enum

from config import MAX_MANA
from game.cv_training import (
    CVTrainingSession,
    DEFAULT_TEMPLATE_BANK_PATH,
    DEFAULT_TRAINING_PROGRESS_PATH,
    get_training_label,
)
from models.cv_track import CVTrack


class GameMode(Enum):
    MENU = "menu"
    SOLO = "solo"
    DUEL = "battle"
    PVE = "pve"
    CV_TRAINING = "cv_training"
    CHARACTER_SELECT = "character_select"
    REMOTE_LOBBY = "remote_lobby"
    REMOTE_DUEL = "remote_duel"


class ModeRunner:
    """Owns per-mode init, per-frame rules, HUD config, and reset logic."""

    def __init__(self, mode: GameMode, training_session_factory=None):
        self.mode = mode
        self.pve_ai = None
        self.pve_paused = False
        self.pve_has_started = False
        self.training_session = None
        self.pending_mode = None
        self._training_session_factory = training_session_factory or (
            lambda: CVTrainingSession(
                progress_path=DEFAULT_TRAINING_PROGRESS_PATH,
                bank_path=DEFAULT_TEMPLATE_BANK_PATH,
            )
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, game, cv_controller):
        """Called once when switching into this mode."""
        cv_controller.tracks = [CVTrack(), CVTrack()]
        if hasattr(cv_controller, "end_training_capture"):
            cv_controller.end_training_capture()

        if self.mode == GameMode.CHARACTER_SELECT:
            if self.pending_mode == GameMode.PVE:
                game.randomize_player_character(1)
            return

        game.reset()

        if self.mode == GameMode.SOLO:
            game.randomize_player_character(1)
        elif self.mode == GameMode.CV_TRAINING:
            game.randomize_player_character(0)
            self.training_session = self._training_session_factory()
            self._sync_training_capture(cv_controller)
        elif self.mode == GameMode.PVE:
            from game.pve_ai import SimplePVEAI

            self.pve_ai = SimplePVEAI()
            self.pve_paused = True
            self.pve_has_started = False
        elif self.mode == GameMode.DUEL:
            pass  # characters are already locked in by character select

    def update(self, frame, game, cv_controller, now, dt):
        """Per-frame: CV input, AI tick, mode-specific rules."""

        if self.mode == GameMode.CV_TRAINING:
            if self.training_session is None:
                self.training_session = self._training_session_factory()
            if not self.training_session.has_pending_review and not self.training_session.is_complete:
                self._sync_training_capture(cv_controller)
                cv_controller.update(frame, game, now, force_player_index=0)
            game.update(dt, now)
            return

        if self.mode == GameMode.PVE and self.pve_paused:
            cv_controller.update(
                frame, game, now,
                force_player_index=0,
                allow_casting=False,
            )
            return

        # --- CV input -------------------------------------------------
        if self.mode in (GameMode.SOLO, GameMode.PVE):
            cv_controller.update(frame, game, now, force_player_index=0)
        else:
            cv_controller.update(frame, game, now)

        # --- PVE AI ---------------------------------------------------
        if self.mode == GameMode.PVE and self.pve_ai is not None:
            self.pve_ai.update(game, now)

        # --- game rules -----------------------------------------------
        game.update(dt, now)
        self._apply_rules(game)

    def reset(self, game):
        game.reset()
        if self.mode == GameMode.SOLO:
            game.randomize_player_character(1)
        elif self.mode == GameMode.CV_TRAINING:
            game.randomize_player_character(0)
        elif self.mode == GameMode.PVE:
            game.randomize_player_character(1)
            if self.pve_ai is not None:
                self.pve_ai.reset()
            self.pve_paused = True
            self.pve_has_started = False
        elif self.mode == GameMode.DUEL:
            pass  # keep locked characters
        if self.training_session is not None:
            self.training_session.reset()

    def toggle_pve_pause(self):
        if self.mode != GameMode.PVE:
            return ""
        if self.pve_paused:
            self.pve_paused = False
            if not self.pve_has_started:
                self.pve_has_started = True
                return "PVE START"
            return "PVE RESUME"
        self.pve_paused = True
        return "PVE PAUSED"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_rules(self, game):
        if self.mode == GameMode.SOLO:
            if game.players[1].hp <= 0 and not game.solo_dummy_defeated:
                game.solo_dummy_defeated = True
            game.winner = None
            game.players[1].mana = MAX_MANA
        elif self.mode == GameMode.PVE:
            if game.players[1].hp <= 0 and not game.solo_dummy_defeated:
                game.solo_dummy_defeated = True
                game.winner = None
            # AI lives with normal mana regen; do not refill.

    # ------------------------------------------------------------------
    # HUD / display properties
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        return {
            GameMode.SOLO: "SOLO SHOWCASE",
            GameMode.DUEL: "DUEL BATTLE",
            GameMode.PVE: "PVE BATTLE",
            GameMode.CV_TRAINING: "CV BANK",
            GameMode.CHARACTER_SELECT: "SELECT CHARACTERS",
            GameMode.REMOTE_LOBBY: "REMOTE DUEL LOBBY",
            GameMode.REMOTE_DUEL: "REMOTE DUEL",
        }.get(self.mode, "")

    @property
    def footer_left(self) -> str | None:
        if self.mode == GameMode.CHARACTER_SELECT:
            return "P1 A/F | P2 J/K cycle   SPACE/ENTER confirm   M menu"
        if self.mode == GameMode.SOLO:
            return "Solo: Q/W/E/R/T or CV gestures = INC/STU/GLA/PRO/LUM   V finger/wand   C lock wand color"
        if self.mode == GameMode.PVE:
            return "P1 Q/W/E/R/T or CV   V input   C lock"
        if self.mode == GameMode.CV_TRAINING:
            return "CV Bank: browse or replace representative gesture slots"
        if self.mode == GameMode.REMOTE_DUEL:
            return "Remote: Q/W/E/R/T or CV   V input   C lock"
        return None

    @property
    def footer_right(self) -> str | None:
        if self.mode == GameMode.CHARACTER_SELECT:
            return None
        if self.mode == GameMode.PVE:
            if self.pve_paused:
                action = "start" if not self.pve_has_started else "resume"
                return f"SPACE {action}   Backspace restart   M menu   ESC back"
            return "SPACE pause   Backspace restart   M menu   ESC back"
        if self.mode == GameMode.SOLO:
            return "SPACE reset   M menu   X quit"
        if self.mode == GameMode.CV_TRAINING:
            return "Enter save   Backspace rerecord   A/D spell   [/ ] slot   4-8 label   M menu"
        if self.mode == GameMode.REMOTE_DUEL:
            return "SPACE rematch after round   M menu   X quit"
        return None

    @property
    def show_solo_overlay(self) -> bool:
        return self.mode in (GameMode.SOLO, GameMode.PVE)

    def solo_dummy_defeated_for_hud(self, game):
        if self.mode == GameMode.PVE and game.winner is not None:
            return None
        if self.show_solo_overlay:
            return game.solo_dummy_defeated
        return None

    @property
    def force_player_index(self) -> int | None:
        if self.mode in (GameMode.SOLO, GameMode.PVE, GameMode.CV_TRAINING):
            return 0
        return None

    @property
    def accepts_p2_keyboard(self) -> bool:
        """P2 keyboard keys only work in Duel mode."""
        return self.mode == GameMode.DUEL

    # ------------------------------------------------------------------
    # CV training
    # ------------------------------------------------------------------

    def _sync_training_capture(self, cv_controller):
        if self.training_session is None or not hasattr(cv_controller, "begin_training_capture"):
            return
        cv_controller.begin_training_capture(
            self.training_session.current_target_spell,
            self._on_training_review,
        )

    def _on_training_review(self, event, track_index):
        if self.training_session is None:
            self.training_session = self._training_session_factory()
        self.training_session.begin_review(
            event,
            points=event.get("points", []),
            track_index=track_index,
        )

    def handle_training_key(self, key, cv_controller):
        if self.mode != GameMode.CV_TRAINING or self.training_session is None:
            return ""

        session = self.training_session
        label_keys = {
            ord("4"): "incendio",
            ord("5"): "circle",
            ord("6"): "glacius",
            ord("7"): "overload",
            ord("8"): "lumos",
        }
        if key in label_keys and session.has_pending_review:
            spell = session.relabel_pending(label_keys[key])
            return f"LABEL: {get_training_label(spell)['label']}" if spell else ""

        if key in (13, 10) and session.has_pending_review:
            saved = session.accept_pending()
            if saved is None:
                self._reset_review_track(cv_controller, "empty training sample")
                self._sync_training_capture(cv_controller)
                return "EMPTY SAMPLE"
            if hasattr(cv_controller, "log_gesture_event"):
                cv_controller.log_gesture_event(saved)
            self._reset_review_track(cv_controller, "training sample saved")
            self._sync_training_capture(cv_controller)
            label = saved.get("intended_spell")
            return f"SAVED {get_training_label(label)['label']}" if label else "SAVED"

        if key in (8, 127, ord(" ")) and session.has_pending_review:
            session.discard_pending()
            self._reset_review_track(cv_controller, "training sample discarded")
            self._sync_training_capture(cv_controller)
            return "DISCARDED SAMPLE"

        if session.has_pending_review:
            return ""

        if key == ord("["):
            session.previous_slot()
            self._reset_review_track(cv_controller, "training slot changed")
            self._sync_training_capture(cv_controller)
            return self._training_slot_notice()

        if key == ord("]"):
            session.next_slot()
            self._reset_review_track(cv_controller, "training slot changed")
            self._sync_training_capture(cv_controller)
            return self._training_slot_notice()

        if key in (ord("a"), ord("A")):
            session.previous_spell()
            self._reset_review_track(cv_controller, "training spell changed")
            self._sync_training_capture(cv_controller)
            return self._training_slot_notice()

        if key in (ord("d"), ord("D")):
            session.next_spell()
            self._reset_review_track(cv_controller, "training spell changed")
            self._sync_training_capture(cv_controller)
            return self._training_slot_notice()

        if key in (8, 127, ord("r"), ord("R")):
            changed = session.clear_current_slot()
            self._reset_review_track(cv_controller, "training slot cleared")
            self._sync_training_capture(cv_controller)
            return "RERECORD SLOT" if changed else "EMPTY SLOT"

        return ""

    def _training_slot_notice(self):
        if self.training_session is None:
            return ""
        label = get_training_label(self.training_session.current_target_spell)["label"]
        slot = self.training_session.current_attempt_number
        total = self.training_session.attempts_per_spell
        status = self.training_session.current_slot_status
        return f"{label} SLOT {slot}/{total} {status}"

    def _reset_review_track(self, cv_controller, detail):
        if self.training_session is None or not hasattr(cv_controller, "reset_cv_track"):
            return
        index = self.training_session.pending_track_index
        track = None
        if hasattr(cv_controller, "tracks") and 0 <= index < len(cv_controller.tracks):
            track = cv_controller.tracks[index]
        cv_controller.reset_cv_track(track, "WAIT", detail)
