from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    tick_rate: int = 30
    snapshot_rate: int = 15
    reconnect_timeout: float = 45.0
    room_idle_timeout: float = 900.0
    max_message_size: int = 16_384
    max_casts_per_second: int = 12
    log_level: str = "INFO"
    max_rooms: int = 1000
    client_send_queue: int = 64

    def __post_init__(self):
        if not self.host:
            raise ValueError("host must not be empty")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.tick_rate <= 0 or self.snapshot_rate <= 0:
            raise ValueError("tick and snapshot rates must be positive")
        if self.snapshot_rate > self.tick_rate:
            raise ValueError("snapshot_rate cannot exceed tick_rate")
        if self.reconnect_timeout <= 0 or self.room_idle_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_message_size < 1024 or self.max_casts_per_second < 1:
            raise ValueError("server limits are invalid")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        if self.max_rooms < 1 or self.client_send_queue < 8:
            raise ValueError("server capacity limits are invalid")

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("SPELLS_SERVER_HOST", "127.0.0.1"),
            port=int(os.getenv("SPELLS_SERVER_PORT", "8765")),
            tick_rate=int(os.getenv("SPELLS_SERVER_TICK_RATE", "30")),
            snapshot_rate=int(os.getenv("SPELLS_SERVER_SNAPSHOT_RATE", "15")),
            reconnect_timeout=float(os.getenv("SPELLS_SERVER_RECONNECT_TIMEOUT", "45")),
            room_idle_timeout=float(os.getenv("SPELLS_SERVER_ROOM_IDLE_TIMEOUT", "900")),
            max_message_size=int(os.getenv("SPELLS_SERVER_MAX_MESSAGE_SIZE", "16384")),
            max_casts_per_second=int(os.getenv("SPELLS_SERVER_MAX_CASTS_PER_SECOND", "12")),
            log_level=os.getenv("SPELLS_SERVER_LOG_LEVEL", "INFO").upper(),
            max_rooms=int(os.getenv("SPELLS_SERVER_MAX_ROOMS", "1000")),
            client_send_queue=int(os.getenv("SPELLS_SERVER_CLIENT_SEND_QUEUE", "64")),
        )
