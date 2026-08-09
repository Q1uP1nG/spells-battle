from __future__ import annotations

import io
import math
import os
import struct
import wave
from typing import Optional

import numpy as np

SAMPLE_RATE = 44100
SFX_DIR = os.path.join("assets", "audio", "sfx")
BGM_DIR = os.path.join("assets", "audio", "bgm")


# ---------------------------------------------------------------------------
# WAV encoding helpers
# ---------------------------------------------------------------------------

def _samples_to_wav_bytes(samples: np.ndarray) -> bytes:
    mono = np.clip(samples, -1.0, 1.0)
    pcm = (mono * 32767).astype(np.int16)
    stereo = np.column_stack([pcm, pcm])
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(stereo.tobytes())
    return buf.getvalue()


def _make_sound(samples: np.ndarray):
    import pygame
    wav_data = _samples_to_wav_bytes(samples)
    return pygame.mixer.Sound(file=io.BytesIO(wav_data))


def _load_sound_file(name: str) -> Optional["pygame.mixer.Sound"]:
    """Try to load a WAV or OGG file from SFX_DIR. Returns None if not found."""
    import pygame
    for ext in (".wav", ".ogg"):
        path = os.path.join(SFX_DIR, name + ext)
        if os.path.isfile(path):
            try:
                return pygame.mixer.Sound(path)
            except Exception as exc:
                print(f"  [audio] failed to load {path}: {exc}")
    return None


# ---------------------------------------------------------------------------
# Waveform primitives
# ---------------------------------------------------------------------------

def _envelope(length: int, attack: float = 0.01, decay: float = 0.1,
              sustain_level: float = 0.6, release: float = 0.3) -> np.ndarray:
    env = np.ones(length, dtype=np.float32)
    attack_n = int(attack * SAMPLE_RATE)
    release_n = int(release * SAMPLE_RATE)
    decay_n = int(decay * SAMPLE_RATE)
    if attack_n > 0:
        env[:attack_n] = np.linspace(0, 1, attack_n, dtype=np.float32)
    if decay_n > 0:
        start = max(attack_n, 0)
        end = min(start + decay_n, length)
        if end > start:
            env[start:end] = np.linspace(1, sustain_level, end - start, dtype=np.float32)
    if attack_n + decay_n < length:
        env[attack_n + decay_n:length - release_n] = sustain_level
    if release_n > 0 and release_n < length:
        env[-release_n:] = np.linspace(sustain_level, 0, release_n, dtype=np.float32)
    return env


def _sine(freq: float, duration: float, phase: float = 0.0) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), dtype=np.float32)
    return np.sin(2 * np.pi * freq * t + phase)


def _saw(freq: float, duration: float) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), dtype=np.float32)
    return 2.0 * (t * freq - np.floor(0.5 + t * freq))


def _noise(duration: float) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    return np.random.randn(n).astype(np.float32) * 0.5


def _lowpass(signal: np.ndarray, cutoff_ratio: float = 0.3) -> np.ndarray:
    n = max(1, int(1.0 / max(cutoff_ratio, 0.01)))
    kernel = np.ones(n, dtype=np.float32) / n
    return np.convolve(signal, kernel, mode="same")


# ---------------------------------------------------------------------------
# Synthesised sound generators (fallbacks when no external file is present)
# ---------------------------------------------------------------------------

def _gen_incendio() -> np.ndarray:
    dur = 0.38
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    freq = 180 + 600 * t / dur
    wave = np.sin(2 * np.pi * freq * t) * 0.45
    wave += _saw(90, dur) * 0.2
    wave += _noise(dur)[:n] * 0.12 * (1 - t / dur)
    env = np.concatenate([
        np.linspace(0, 1, int(n * 0.08)),
        np.linspace(1, 0.6, int(n * 0.3)),
        np.linspace(0.6, 0, n - int(n * 0.08) - int(n * 0.3)),
    ])
    return wave * env[:n] * 0.55


def _gen_stupefy() -> np.ndarray:
    dur = 0.32
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    wave = np.sin(2 * np.pi * 420 * t) * 0.35
    crack = np.zeros(n, dtype=np.float32)
    for pos in [0.02, 0.08, 0.16, 0.25]:
        idx = int(pos * SAMPLE_RATE)
        if 0 <= idx < n:
            burst_len = min(int(0.015 * SAMPLE_RATE), n - idx)
            crack[idx:idx + burst_len] += np.random.randn(burst_len).astype(np.float32) * 0.6
    wave += crack
    env = np.concatenate([
        np.linspace(0, 1, int(n * 0.04)),
        np.linspace(1, 0, n - int(n * 0.04)),
    ])
    return wave * env[:n] * 0.5


def _gen_glacius() -> np.ndarray:
    dur = 0.45
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    freq = 900 * np.exp(-3.5 * t)
    wave = np.sin(2 * np.pi * freq * t) * 0.4
    wave += np.sin(2 * np.pi * freq * 1.5 * t) * 0.15
    noise = _noise(dur)[:n] * 0.08 * (1 - t / dur)
    wave += _lowpass(noise, 0.15)
    env = np.concatenate([
        np.linspace(0, 1, int(n * 0.05)),
        np.linspace(1, 0.35, int(n * 0.5)),
        np.linspace(0.35, 0, n - int(n * 0.05) - int(n * 0.5)),
    ])
    return wave * env[:n] * 0.55


def _gen_protego() -> np.ndarray:
    dur = 0.55
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    wave = _sine(280, dur) * 0.25
    wave += _sine(560, dur) * 0.2
    wave += _sine(840, dur) * 0.1
    env = np.concatenate([
        np.linspace(0, 1, int(n * 0.06)),
        np.ones(int(n * 0.35)) * 0.85,
        np.linspace(0.85, 0, n - int(n * 0.06) - int(n * 0.35)),
    ])
    shimmer = 0.15 * np.sin(2 * np.pi * 6 * t)
    return (wave + shimmer) * env[:n] * 0.45


def _gen_lumos() -> np.ndarray:
    dur = 0.6
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    freq = 500 + 200 * t / dur
    wave = np.sin(2 * np.pi * freq * t) * 0.35
    wave += _sine(750, dur) * 0.15
    wave += _sine(1000, dur) * 0.08
    env = np.concatenate([
        np.linspace(0, 1, int(n * 0.1)),
        np.linspace(1, 0.55, int(n * 0.5)),
        np.linspace(0.55, 0, n - int(n * 0.1) - int(n * 0.5)),
    ])
    return wave * env[:n] * 0.4


def _gen_hit() -> np.ndarray:
    dur = 0.22
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    low = np.sin(2 * np.pi * 90 * t) * 0.45 * np.exp(-8 * t)
    mid = np.sin(2 * np.pi * 220 * t) * 0.2 * np.exp(-12 * t)
    noise = _noise(dur)[:n] * 0.15 * np.exp(-15 * t)
    return (low + mid + noise) * 0.6


def _gen_shield_hit() -> np.ndarray:
    dur = 0.35
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    ring = np.sin(2 * np.pi * 650 * t) * 0.35 * np.exp(-5 * t)
    ring += np.sin(2 * np.pi * 980 * t) * 0.15 * np.exp(-6 * t)
    impact = np.sin(2 * np.pi * 120 * t) * 0.25 * np.exp(-10 * t)
    return (ring + impact) * 0.5


def _gen_cast_fail() -> np.ndarray:
    dur = 0.15
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    wave = np.sin(2 * np.pi * 80 * t) * 0.25 * np.exp(-20 * t)
    wave += np.sin(2 * np.pi * 55 * t) * 0.2 * np.exp(-18 * t)
    click = np.zeros(n, dtype=np.float32)
    burst_len = min(int(0.02 * SAMPLE_RATE), n)
    click[:burst_len] += np.random.randn(burst_len).astype(np.float32) * 0.3
    return (wave + click) * 0.4


def _gen_menu_select() -> np.ndarray:
    dur = 0.12
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    wave = _sine(660, dur) * 0.25 * _envelope(n, attack=0.005, decay=0.02, release=0.06)
    wave += _sine(880, dur) * 0.15 * _envelope(n, attack=0.005, decay=0.02, release=0.06)
    return wave


def _gen_round_over() -> np.ndarray:
    dur = 1.2
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    notes = [(_sine(440, dur) * 0.3 * np.exp(-2 * t)),
             (_sine(554, dur) * 0.25 * np.exp(-3 * t)),
             (_sine(659, dur) * 0.2 * np.exp(-4 * t))]
    return sum(notes) * 0.45


def _gen_clash_fire_lightning() -> np.ndarray:
    dur = 0.42
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    fire = _saw(95, dur) * 0.20 * np.exp(-4.0 * t)
    fire += _noise(dur)[:n] * 0.18 * np.exp(-8.0 * t)
    lightning = np.zeros(n, dtype=np.float32)
    for pos in (0.02, 0.07, 0.14, 0.23):
        idx = int(pos * SAMPLE_RATE)
        burst_len = min(int(0.018 * SAMPLE_RATE), n - idx)
        if burst_len > 0:
            lightning[idx:idx + burst_len] += (
                np.random.randn(burst_len).astype(np.float32) * 0.55
            )
    ring = _sine(740, dur) * 0.12 * np.exp(-5.0 * t)
    return (fire + lightning + ring) * 0.55


def _gen_clash_lightning_ice() -> np.ndarray:
    dur = 0.44
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    zap = _sine(520, dur) * 0.28 * np.exp(-6.0 * t)
    zap += _noise(dur)[:n] * 0.20 * np.exp(-10.0 * t)
    ice_ring = _sine(1100, dur) * 0.18 * np.exp(-3.5 * t)
    ice_ring += _sine(1470, dur) * 0.08 * np.exp(-4.0 * t)
    return (zap + ice_ring) * 0.52


def _gen_clash_ice_fire() -> np.ndarray:
    dur = 0.48
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    cold = _sine(980, dur) * 0.25 * np.exp(-3.0 * t)
    cold += _lowpass(_noise(dur)[:n], 0.12) * 0.12 * np.exp(-4.0 * t)
    steam = _noise(dur)[:n] * 0.16 * np.exp(-7.5 * t)
    low_hit = _sine(120, dur) * 0.16 * np.exp(-9.0 * t)
    return (cold + steam + low_hit) * 0.50


def _gen_clash_cancel() -> np.ndarray:
    dur = 0.32
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    impact = _sine(180, dur) * 0.24 * np.exp(-9.0 * t)
    shimmer = _sine(680, dur) * 0.18 * np.exp(-6.0 * t)
    dust = _noise(dur)[:n] * 0.12 * np.exp(-12.0 * t)
    return (impact + shimmer + dust) * 0.48


def _gen_ambient_loop() -> np.ndarray:
    dur = 4.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, dtype=np.float32)
    base = np.sin(2 * np.pi * 55 * t) * 0.06
    base += np.sin(2 * np.pi * 82.5 * t) * 0.04
    base += np.sin(2 * np.pi * 110 * t * (1 + 0.02 * np.sin(2 * np.pi * 0.3 * t))) * 0.03
    drift = np.sin(2 * np.pi * 0.25 * t) * 0.01
    noise_band = _lowpass(_noise(dur)[:n], 0.03) * 0.025
    loop = base + drift + noise_band
    fade = int(0.5 * SAMPLE_RATE)
    loop[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    loop[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return loop * 0.12


SOUND_GENERATORS = {
    "incendio": _gen_incendio,
    "stupefy": _gen_stupefy,
    "glacius": _gen_glacius,
    "protego": _gen_protego,
    "lumos": _gen_lumos,
    "hit": _gen_hit,
    "shield_hit": _gen_shield_hit,
    "cast_fail": _gen_cast_fail,
    "menu_select": _gen_menu_select,
    "round_over": _gen_round_over,
    "clash_fire_lightning": _gen_clash_fire_lightning,
    "clash_lightning_ice": _gen_clash_lightning_ice,
    "clash_ice_fire": _gen_clash_ice_fire,
    "clash_cancel": _gen_clash_cancel,
}


# ---------------------------------------------------------------------------
# AudioManager
# ---------------------------------------------------------------------------

class AudioManager:
    def __init__(self, bgm_volume: float = 0.3, sfx_volume: float = 0.7):
        self._initialized = False
        self._sounds: dict = {}
        self._bgm_sound = None
        self._bgm_channel = None
        self._bgm_volume = max(0.0, min(1.0, bgm_volume))
        self._sfx_volume = max(0.0, min(1.0, sfx_volume))
        self._muted = False

    # --- init ----------------------------------------------------------

    def init(self) -> bool:
        try:
            import pygame
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=1024)
            self._generate_all()
            self._load_bgm()
            self._initialized = True
            return True
        except Exception as exc:
            print(f"Audio init failed: {exc}")
            return False

    def _generate_all(self):
        for name in SOUND_GENERATORS:
            sound = _load_sound_file(name) or _make_sound(SOUND_GENERATORS[name]())
            sound.set_volume(self._sfx_volume)
            self._sounds[name] = sound

    def _load_bgm(self):
        for ext in (".wav", ".ogg"):
            path = os.path.join(BGM_DIR, "battle_loop" + ext)
            if os.path.isfile(path):
                try:
                    import pygame
                    self._bgm_sound = pygame.mixer.Sound(path)
                    self._bgm_sound.set_volume(self._bgm_volume)
                    return
                except Exception:
                    pass
        self._bgm_sound = _make_sound(_gen_ambient_loop())
        self._bgm_sound.set_volume(self._bgm_volume)

    # --- internal ------------------------------------------------------

    def _play(self, name: str):
        """Play a named sound effect on an available channel."""
        if not self._initialized or self._muted:
            return
        sound = self._sounds.get(name)
        if sound is None:
            return
        import pygame
        ch = pygame.mixer.find_channel() if pygame.mixer.get_init() else None
        if ch is not None:
            ch.play(sound)

    # --- public play methods -------------------------------------------

    def play_cast(self, spell_name: str):
        self._play(spell_name)

    def play_hit(self):
        self._play("hit")

    def play_shield_hit(self):
        self._play("shield_hit")

    def play_cast_fail(self):
        self._play("cast_fail")

    def play_menu_select(self):
        self._play("menu_select")

    def play_round_over(self):
        self._play("round_over")

    def play_effect(self, name: str):
        self._play(name)

    # --- BGM -----------------------------------------------------------

    def start_bgm(self):
        if not self._initialized or self._muted:
            return
        import pygame
        if self._bgm_channel is not None and self._bgm_channel.get_busy():
            return
        self._bgm_channel = pygame.mixer.Channel(0)
        self._bgm_channel.play(self._bgm_sound, loops=-1)

    def stop_bgm(self):
        if not self._initialized:
            return
        if self._bgm_channel is not None:
            self._bgm_channel.stop()

    # --- volume / mute ------------------------------------------------

    def set_sfx_volume(self, volume: float):
        self._sfx_volume = max(0.0, min(1.0, volume))
        for sound in self._sounds.values():
            sound.set_volume(self._sfx_volume)

    def set_bgm_volume(self, volume: float):
        self._bgm_volume = max(0.0, min(1.0, volume))
        if self._bgm_sound is not None:
            self._bgm_sound.set_volume(self._bgm_volume)

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        if self._muted:
            self.stop_bgm()
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def available(self) -> bool:
        return self._initialized
