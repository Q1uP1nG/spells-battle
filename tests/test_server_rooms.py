import unittest

from game.commands import CastIntent
from server.room import RoomError, RoomState
from server.room_manager import RoomManager


class ServerRoomTests(unittest.TestCase):
    def make_full_room(self):
        manager = RoomManager(reconnect_timeout=5.0, room_idle_timeout=30.0)
        room, first = manager.create_room(10.0)
        _, second = manager.join_room(room.room_code, 10.1)
        return manager, room, first, second

    def test_create_and_join_assign_server_owned_seats(self):
        _, room, first, second = self.make_full_room()

        self.assertEqual((first.player_index, second.player_index), (0, 1))
        self.assertNotEqual(first.reconnect_token, second.reconnect_token)
        self.assertEqual(room.state, RoomState.READY_CHECK)

        with self.assertRaises(RoomError) as error:
            room.add_player(11.0)
        self.assertEqual(error.exception.code, "room_full")

    def test_two_ready_players_start_authoritative_session(self):
        _, room, _, _ = self.make_full_room()

        room.set_ready(0, True, 11.0)
        room.set_ready(1, True, 11.1)

        self.assertEqual(room.state, RoomState.RUNNING)
        self.assertIsNotNone(room.session)
        self.assertEqual(room.session.server_tick, 0)

    def test_duplicate_sequence_is_rejected_without_second_cast(self):
        _, room, _, _ = self.make_full_room()
        room.set_ready(0, True, 11.0)
        room.set_ready(1, True, 11.0)
        intent = CastIntent("incendio", 1, 0, "keyboard")

        accepted, events = room.submit_cast(0, intent, 12.0)

        self.assertTrue(accepted)
        self.assertEqual(len(room.session.engine.projectiles), 1)
        self.assertEqual(events[0].kind, "cast_accepted")
        with self.assertRaises(RoomError) as error:
            room.submit_cast(0, intent, 12.1)
        self.assertEqual(error.exception.code, "duplicate_sequence")
        self.assertEqual(len(room.session.engine.projectiles), 1)

    def test_disconnect_pauses_and_valid_token_reconnects(self):
        _, room, first, _ = self.make_full_room()
        room.set_ready(0, True, 11.0)
        room.set_ready(1, True, 11.0)
        room.disconnect(0, 12.0)

        room.step(1.0)

        self.assertTrue(room.paused)
        self.assertEqual(room.session.server_tick, 0)
        restored = room.reconnect(first.reconnect_token, 13.0)
        self.assertEqual(restored.player_index, 0)
        self.assertFalse(room.paused)

    def test_expired_reconnect_closes_room_during_cleanup(self):
        manager, room, _, _ = self.make_full_room()
        room.disconnect(1, 20.0)

        removed = manager.cleanup(25.1)

        self.assertEqual(removed, [room.room_code])
        self.assertEqual(room.state, RoomState.CLOSED)

    def test_both_players_must_request_rematch_before_new_round(self):
        _, room, _, _ = self.make_full_room()
        room.set_ready(0, True, 11.0)
        room.set_ready(1, True, 11.0)
        previous_match_id = room.match_id
        room.state = RoomState.ROUND_OVER

        room.request_rematch(0, 12.0)
        self.assertEqual(room.state, RoomState.ROUND_OVER)
        room.request_rematch(1, 12.1)

        self.assertEqual(room.state, RoomState.RUNNING)
        self.assertNotEqual(room.match_id, previous_match_id)
        self.assertEqual(room.session.server_tick, 0)

    def test_room_capacity_is_explicitly_limited(self):
        manager = RoomManager(max_rooms=1)
        manager.create_room(1.0)

        with self.assertRaises(RoomError) as error:
            manager.create_room(2.0)

        self.assertEqual(error.exception.code, "server_capacity")


if __name__ == "__main__":
    unittest.main()
