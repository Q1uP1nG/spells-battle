import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from cv.controller import create_default_gesture_pipeline
from cv.gesture_pipeline import FusedGestureClassifier
from cv.template_classifier import DataTemplateClassifier
from game.battle_engine import BattleEngine, DRAW
from game.snapshots import PROTOCOL_VERSION, snapshot_from_engine
from network.protocol import (ProtocolError, decode_message, event_from_payload,
                              event_to_payload, snapshot_from_payload, snapshot_to_payload)
from server.room import Room, RoomState


class CoreRobustnessTests(unittest.TestCase):
    def test_invalid_trajectories_never_cast_including_shadow_pipeline(self):
        classifiers = [DataTemplateClassifier(), FusedGestureClassifier(),
                       create_default_gesture_pipeline()]
        for points in (None, [], [[float("nan"), 0]] * 20,
                       [[float("inf"), 0]] * 20, [[0, 0], [1]] * 10,
                       [["bad", 0]] * 20, [[0, 0, 0]] * 20):
            for classifier in classifiers:
                with self.subTest(points=str(points)[:30], classifier=type(classifier).__name__):
                    result = classifier.classify(points, "left")
                    self.assertIsNone(result.spell)
                    self.assertEqual(result.confidence, 0.0)

    def test_numpy_input_matches_list_input(self):
        points = [[i * 12, 0] for i in range(20)]
        classifier = create_default_gesture_pipeline()
        expected = classifier.classify(points, "left")
        actual = classifier.classify(np.asarray(points), "left")
        self.assertEqual(actual.spell, "incendio")
        self.assertEqual(actual.confidence, expected.confidence)

    def test_incendio_requires_advance_toward_opponent_on_both_sides(self):
        for side, toward in (("left", 1), ("right", -1)):
            for classifier in (DataTemplateClassifier(), create_default_gesture_pipeline()):
                with self.subTest(side=side, classifier=type(classifier).__name__):
                    points = [[toward * i * 12, 0] for i in range(20)]
                    self.assertEqual(classifier.classify(points, side).spell, "incendio")
                    backward = [[-x, y] for x, y in points]
                    self.assertIsNone(classifier.classify(backward, side).spell)

    def test_invalid_template_pack_is_rejected_without_partial_load(self):
        valid = [[i / 31, 0] for i in range(32)]
        packs = [
            {"target_point_count": "bad"},
            {"prototypes": {"incendio": [["bad"]]}},
            {"prototypes": {"incendio": [[[float("nan"), 0]] * 32]}},
            {"prototypes": {"unknown_spell": [valid]}},
            {"prototypes": {"incendio": [valid]}, "thresholds": {"incendio": float("inf")}},
            {"prototypes": {"incendio": [valid]}, "margin_thresholds": {"incendio": -1}},
            {"prototypes": {"incendio": [valid], "lumos": [["bad"]]}},
        ]
        for payload in packs:
            with self.subTest(payload=str(payload)[:80]):
                classifier = DataTemplateClassifier(template_payload=payload)
                self.assertFalse(classifier.loaded)
                self.assertEqual(classifier.spells, ())
                self.assertIn("invalid", classifier.load_error)

    def test_corrupt_file_allows_default_pipeline_to_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "templates.json"
            path.write_text('{"target_point_count":"bad"}', encoding="utf-8")
            pipeline = create_default_gesture_pipeline(data_template_path=path)
            result = pipeline.classify([[i * 12, 0] for i in range(20)], "left")
            self.assertEqual(result.spell, "incendio")

    def test_malformed_message_types_are_protocol_errors(self):
        for kind in ([], {}, None, True, 12):
            with self.subTest(kind=kind):
                with self.assertRaises(ProtocolError) as error:
                    decode_message(json.dumps({"protocol_version": PROTOCOL_VERSION,
                                               "type": kind, "payload": {}}))
                self.assertEqual(error.exception.code, "unknown_type")

    def test_previous_protocol_is_explicitly_rejected(self):
        with self.assertRaises(ProtocolError) as error:
            decode_message(json.dumps({"protocol_version": PROTOCOL_VERSION - 1,
                                       "type": "ping", "payload": {}}))
        self.assertEqual(error.exception.code, "version_mismatch")

    def test_remote_session_applies_draw_snapshot(self):
        from game.remote_session import RemoteBattleSession
        engine = BattleEngine()
        engine.winner = DRAW
        session = RemoteBattleSession(network_client=object())
        session.match_id = "draw-match"
        snapshot = snapshot_from_engine(engine, "draw-match", 1, 0)
        session._handle_message({"type": "battle_snapshot",
                                 "payload": snapshot_to_payload(snapshot)}, 0)
        self.assertEqual(session.game.winner, DRAW)

    def test_simultaneous_hits_draw_and_end_once_with_rematch(self):
        room = Room("ABC123", 0)
        room.add_player(0)
        room.add_player(0)
        room.set_ready(0, True, 0)
        room.set_ready(1, True, 0)
        engine = room.session.engine
        for player in engine.players:
            player.hp = 1
            engine.cast_spell(player.pid, "incendio", 0)
        for projectile in engine.projectiles:
            projectile.pos[:] = engine.players[1 - projectile.owner].center()
            projectile.vel[:] = 0
        events = room.step(0)
        self.assertEqual(engine.winner, DRAW)
        self.assertEqual(room.state, RoomState.ROUND_OVER)
        ended = [event for event in events if event.kind == "round_ended"]
        self.assertEqual(len(ended), 1)
        self.assertEqual(event_from_payload(event_to_payload(ended[0])).payload["winner"], DRAW)
        snapshot = snapshot_from_engine(engine, room.match_id, 1, 0)
        self.assertEqual(snapshot_from_payload(snapshot_to_payload(snapshot)).winner, DRAW)
        self.assertEqual(room.step(0), [])
        room.request_rematch(0, 1)
        room.request_rematch(1, 1)
        self.assertEqual(room.state, RoomState.RUNNING)
        self.assertIsNone(room.session.engine.winner)

    def test_hud_displays_draw_without_selecting_a_winner(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.hud import draw_hud
        game = BattleGame()
        game.winner = DRAW
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        with patch("renderer.hud.draw_centered_text") as text:
            draw_hud(frame, game, 0, 60, "CV OFF")
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn("DRAW", labels)
        self.assertFalse(any("WINS" in str(label) for label in labels))
