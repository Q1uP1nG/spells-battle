import json
import unittest

from game.battle_engine import BattleEngine
from game.commands import CastIntent
from game.events import BattleEvent
from game.snapshots import snapshot_from_engine
from network.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    cast_intent_from_payload,
    cast_intent_to_payload,
    decode_message,
    encode_message,
    event_from_payload,
    event_to_payload,
    snapshot_from_payload,
    snapshot_to_payload,
)


class ProtocolTests(unittest.TestCase):
    def test_cast_command_round_trip(self):
        intent = CastIntent("stupefy", 3, 1450, "cv")

        raw = encode_message(
            "cast", cast_intent_to_payload(intent, match_id="match-3"), request_id="request-3"
        )
        message = decode_message(raw)

        self.assertEqual(cast_intent_from_payload(message["payload"]), intent)
        self.assertEqual(message["payload"]["match_id"], "match-3")
        self.assertEqual(message["request_id"], "request-3")

    def test_event_round_trip(self):
        event = BattleEvent(
            7, "player_hit", 2.5, {"damage": 12.0}, server_tick=45, match_id="match-7"
        )

        raw = encode_message("battle_event", event_to_payload(event))
        restored = event_from_payload(decode_message(raw)["payload"])

        self.assertEqual(restored, event)

    def test_snapshot_round_trip_through_envelope(self):
        engine = BattleEngine()
        snapshot = snapshot_from_engine(engine, "match-2", 9, 0.3)

        raw = encode_message("battle_snapshot", snapshot_to_payload(snapshot))
        restored = snapshot_from_payload(decode_message(raw)["payload"])

        self.assertEqual(restored, snapshot)

    def test_unknown_optional_fields_are_ignored(self):
        intent = CastIntent("lumos", 1, 0, "keyboard")
        payload = cast_intent_to_payload(intent)
        payload["future_optional_field"] = {"enabled": True}
        raw = json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "cast",
                "payload": payload,
                "future_envelope_field": "ignored",
            }
        )

        restored = cast_intent_from_payload(decode_message(raw)["payload"])

        self.assertEqual(restored, intent)

    def test_missing_required_envelope_field_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "missing required"):
            decode_message(json.dumps({"protocol_version": PROTOCOL_VERSION, "type": "cast"}))

    def test_missing_required_cast_field_is_rejected(self):
        with self.assertRaises(ProtocolError) as error:
            cast_intent_from_payload(
                {"spell": "lumos", "sequence": 1, "client_time_ms": 0}
            )

        self.assertEqual(error.exception.code, "missing_field")

    def test_version_mismatch_is_rejected(self):
        raw = json.dumps(
            {"protocol_version": PROTOCOL_VERSION + 1, "type": "ping", "payload": {}}
        )

        with self.assertRaises(ProtocolError) as error:
            decode_message(raw)

        self.assertEqual(error.exception.code, "version_mismatch")

    def test_unknown_message_type_is_rejected(self):
        raw = json.dumps(
            {"protocol_version": PROTOCOL_VERSION, "type": "take_control", "payload": {}}
        )

        with self.assertRaises(ProtocolError) as error:
            decode_message(raw)

        self.assertEqual(error.exception.code, "unknown_type")

    def test_duplicate_json_fields_are_rejected(self):
        raw = (
            f'{{"protocol_version":{PROTOCOL_VERSION},"type":"ping",'
            '"type":"pong","payload":{}}'
        )

        with self.assertRaises(ProtocolError) as error:
            decode_message(raw)

        self.assertEqual(error.exception.code, "duplicate_field")

    def test_invalid_json_and_non_object_payload_are_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_message("not-json")
        with self.assertRaises(ProtocolError):
            decode_message(
                json.dumps({"protocol_version": PROTOCOL_VERSION, "type": "ping", "payload": []})
            )

    def test_non_finite_numbers_cannot_be_encoded(self):
        with self.assertRaises(ValueError):
            encode_message("ping", {"time": float("nan")})


if __name__ == "__main__":
    unittest.main()
