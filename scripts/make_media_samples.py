"""Generate REAL short video/audio clips for the sample pack, so the ingestion
pipeline actually WATCHES video and HEARS audio with Gemini — not filenames.

    python scripts/make_media_samples.py

Writes genuine (small) media into sample_assets/video and sample_assets/audio,
replacing the byte-stub placeholders. Video is synthesized frame-by-frame with
imageio (+ imageio-ffmpeg); audio is 16-bit PCM WAV via the stdlib `wave` module
(no extra dependency). These are procedurally generated — not stock footage — but
they are real, decodable media with genuine motion and sound that Gemini can
describe from content. Swap in real footage before the final recording for extra
polish; the pipeline handles both identically.

Pairs with make_sample_pack.py (raster images). Together they produce a demo
library with real pixels, motion, sound, an exact-duplicate pair, and a
project-specific asset that should sink in the reusability ranking.
"""
from __future__ import annotations

import math
import os
import shutil
import struct
import wave

import imageio.v2 as imageio
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_assets")

FPS = 12
SIZE = (480, 270)  # (w, h) — small, quick to encode, still clearly readable


def _writer(rel: str):
    full = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    # libx264 in an mp4/mov container — widely decodable, small files.
    return full, imageio.get_writer(full, fps=FPS, codec="libx264",
                                    quality=6, macro_block_size=None)


def _grad(top, bottom):
    """Vertical gradient frame as an (h, w, 3) uint8 array."""
    w, h = SIZE
    t = np.linspace(0.0, 1.0, h)[:, None]
    row = (np.array(top) * (1 - t) + np.array(bottom) * t).astype(np.uint8)
    return np.repeat(row[:, None, :], w, axis=1)


def _rect(frame, x0, y0, x1, y1, color):
    w, h = SIZE
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 > x0 and y1 > y0:
        frame[y0:y1, x0:x1] = color


def make_city_broll(rel: str, seconds: float = 5.0) -> str:
    """Dusk city skyline with lit windows flickering and a light panning across —
    genuine motion, reads clearly as reusable establishing b-roll."""
    full, w = _writer(rel)
    w_px, h_px = SIZE
    n = int(seconds * FPS)
    buildings = [(x, 90 + (i % 4) * 22, 46) for i, x in enumerate(range(20, w_px - 30, 52))]
    for f in range(n):
        frame = _grad((28, 44, 92), (8, 12, 30))
        for bi, (bx, top, bw) in enumerate(buildings):
            _rect(frame, bx, top, bx + bw, h_px - 20, (18, 22, 40))
            for wy in range(top + 8, h_px - 26, 14):
                for wx in range(bx + 6, bx + bw - 6, 12):
                    lit = (math.sin(f * 0.5 + wx * 0.7 + wy) > 0.2)
                    _rect(frame, wx, wy, wx + 6, wy + 7,
                          (240, 220, 140) if lit else (30, 34, 52))
        # A light panning left→right across the skyline.
        lx = int((f / max(1, n - 1)) * w_px)
        _rect(frame, lx - 3, 0, lx + 3, h_px, (250, 240, 210))
        w.append_data(frame)
    w.close()
    return full


def make_rough_cut(rel: str, seconds: float = 4.0) -> str:
    """A slate/timecode 'rough cut' look — clearly project-specific, not stock."""
    full, w = _writer(rel)
    w_px, h_px = SIZE
    n = int(seconds * FPS)
    for f in range(n):
        frame = np.full((h_px, w_px, 3), 18, dtype=np.uint8)
        _rect(frame, 16, 16, w_px - 16, h_px - 16, (40, 40, 40))
        # Sweeping "scan" bar + a moving timecode block to read as an edit.
        bar = int((f / max(1, n - 1)) * (w_px - 60)) + 30
        _rect(frame, bar, 20, bar + 8, h_px - 20, (90, 90, 90))
        tc = 30 + f
        _rect(frame, 30, h_px - 44, 30 + (tc % 120), h_px - 34, (200, 60, 60))
        w.append_data(frame)
    w.close()
    return full


def make_ocean_broll(rel: str, seconds: float = 5.0) -> str:
    """Warm ocean-horizon b-roll with a rolling band — a second reusable clip."""
    full, w = _writer(rel)
    w_px, h_px = SIZE
    n = int(seconds * FPS)
    for f in range(n):
        frame = _grad((255, 170, 80), (120, 40, 90))
        horizon = h_px // 2
        _rect(frame, 0, horizon, w_px, h_px, (20, 40, 90))
        # Rolling wave band.
        for x in range(w_px):
            y = horizon + int(10 * math.sin(x * 0.06 + f * 0.4))
            _rect(frame, x, y, x + 1, y + 4, (200, 220, 240))
        w.append_data(frame)
    w.close()
    return full


def _write_wav(rel: str, samples: np.ndarray, rate: int = 22050) -> str:
    """Write a mono 16-bit PCM WAV from a float array in [-1, 1]."""
    full = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype("<i2").tobytes()
    with wave.open(full, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return full


def make_whoosh(rel: str, seconds: float = 1.2, rate: int = 22050) -> str:
    """A rising-then-falling filtered-noise whoosh — a reusable transition SFX."""
    n = int(seconds * rate)
    t = np.linspace(0, seconds, n, endpoint=False)
    env = np.sin(np.pi * t / seconds) ** 2          # smooth swell
    noise = np.random.default_rng(7).standard_normal(n)
    # Cheap low-pass that opens up over time (brightens the whoosh).
    swept = np.cumsum(noise) / np.arange(1, n + 1)
    return _write_wav(rel, env * (swept / (np.abs(swept).max() or 1)), rate)


def make_ambient(rel: str, seconds: float = 4.0, rate: int = 22050) -> str:
    """A low ambient city bed: rumble + faint airy noise — reusable music/ambience."""
    n = int(seconds * rate)
    t = np.linspace(0, seconds, n, endpoint=False)
    rumble = 0.4 * np.sin(2 * np.pi * 70 * t) + 0.2 * np.sin(2 * np.pi * 55 * t)
    air = 0.05 * np.random.default_rng(3).standard_normal(n)
    return _write_wav(rel, 0.6 * (rumble + air), rate)


def make_voiceover(rel: str, seconds: float = 3.0, rate: int = 22050) -> str:
    """An amplitude-modulated mid tone standing in for host narration cadence —
    project-specific (a real VO recorded for one scene), should NOT be reusable."""
    n = int(seconds * rate)
    t = np.linspace(0, seconds, n, endpoint=False)
    speech = np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    return _write_wav(rel, 0.5 * speech, rate)


def main() -> None:
    # Video ----------------------------------------------------------------
    city = make_city_broll("video/city_broll_01.mp4")
    # Exact duplicate: copy the encoded bytes so content_hash matches exactly.
    dup = os.path.join(ROOT, "video/city_broll_01_copy.mp4")
    shutil.copyfile(city, dup)
    print("  wrote video/city_broll_01.mp4 (+ exact copy)")
    make_rough_cut("video/project_rough_cut_v3.mov")
    print("  wrote video/project_rough_cut_v3.mov")
    make_ocean_broll("video/ocean_waves_broll.mp4")
    print("  wrote video/ocean_waves_broll.mp4")

    # Audio ----------------------------------------------------------------
    make_whoosh("audio/whoosh_sfx.wav")
    print("  wrote audio/whoosh_sfx.wav")
    make_ambient("audio/ambient_city.wav")
    print("  wrote audio/ambient_city.wav")
    make_voiceover("audio/voiceover_host_scene4.wav")
    print("  wrote audio/voiceover_host_scene4.wav")

    # Remove the old byte-stub .mp3 that this script supersedes with a real .wav.
    old_mp3 = os.path.join(ROOT, "audio/ambient_city.mp3")
    if os.path.isfile(old_mp3) and os.path.getsize(old_mp3) < 1024:
        os.remove(old_mp3)
        print("  removed stub audio/ambient_city.mp3 (replaced by .wav)")

    print("Real media samples ready in", ROOT)


if __name__ == "__main__":
    main()
