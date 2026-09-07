"""Fetch a small, real, royalty-free demo library for xStoreAgent.

Downloads a handful of Mixkit (no key) — or Pexels, if PEXELS_API_KEY is set —
city / product clips, trims them to 6s 720p so Gemini ingest stays cheap, and
lays them over the generated brand kit, clapper slate, rough-cut, and VO.

The 5,000-row scale story is still `scripts/seed_scale.py`. Do not point ingest
at a camera-card dump.

    python scripts/fetch_demo_pack.py
    python scripts/fetch_demo_pack.py --pexels-key YOUR_KEY
    python scripts/fetch_demo_pack.py --mixkit-only

Then:

    python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "sample_assets"
SCRIPTS = Path(__file__).resolve().parent

UA = {
    "User-Agent": (
        "xStoreAgent-demo-pack/1.0 (hackathon librarian demo; "
        "https://github.com/)"
    )
}
BROWSER_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

VIDEO_SECONDS = 6.0
VIDEO_SIZE = (1280, 720)
# Keep a little audio on these so the Curator can *hear* the clip on camera.
KEEP_AUDIO = {"city_skyline_dusk_broll.mp4"}

# Mixkit Free License, no attribution required. IDs verified against
# assets.mixkit.co/{id}/{id}-720.mp4 (falls back to -360).
MIXKIT_VIDEOS: dict[str, int] = {
    "city_skyline_dusk_broll.mp4": 42342,          # aerial city at night
    "neon_street_night_broll.mp4": 6754,           # street traffic by night
    "crowd_crossing_broll.mp4": 4401,              # crowds at a junction
    "product_hero_macro.mp4": 3649,                # wrist-watch close-up
    "cafe_window_golden_hour.mp4": 4350,           # urban coffee shop
    "aerial_downtown_establishing.mp4": 56,        # daytime aerial traffic
}
MIXKIT_STILL_VIDEOS: dict[str, int] = {
    "forest_nature.jpg": 5040,                     # leftover other-project stock
    "sunset_beach.jpg": 2168,                      # leftover beach campaign
}
MIXKIT_SFX: dict[str, int] = {
    "whoosh_sfx.wav": 1489,
    "ambient_city.wav": 1554,
}
MIXKIT_MUSIC_ID = 644  # upbeat bed, trimmed to 8s

PEXELS_VIDEO_QUERIES: dict[str, str] = {
    "city_skyline_dusk_broll.mp4": "city skyline dusk aerial",
    "neon_street_night_broll.mp4": "night neon city street traffic",
    "crowd_crossing_broll.mp4": "crowd crossing downtown street",
    "product_hero_macro.mp4": "wrist watch close up product",
    "cafe_window_golden_hour.mp4": "cafe window golden hour",
    "aerial_downtown_establishing.mp4": "aerial downtown city traffic",
}
PEXELS_PHOTO_QUERIES: dict[str, str] = {
    "city_skyline.jpg": "city skyline dusk",
    "product_hero.jpg": "wrist watch product",
    "neon_street.jpg": "neon city street night",
    "forest_nature.jpg": "forest canopy trees",
    "sunset_beach.jpg": "sunset beach",
}

# Synthetic files that would otherwise be ingested next to the real pack.
LEGACY = [
    "video/city_broll_01.mp4",
    "video/city_broll_01_copy.mp4",
    "video/ocean_waves_broll.mp4",
    "images/city_skyline.png",
    "images/city_skyline_dup.png",
    "images/forest_nature.png",
]

NOTES = """Shot list — Lumen Watch, 30s city product ad

Beats: hook (aerial dusk) → establish (street / crowd) → product (watch macro)
→ proof (cafe window) → CTA (logo). Music: 8s upbeat bed. SFX: whoosh.

Reuse from this drive: city/neon/crowd/product/cafe B-roll, logo, whoosh, bed.
Project-specific (do not reuse): scene 12 take 3 slate, rough_cut_v3, host VO.
Leftover from other shoots (still reusable): forest still, sunset beach still.

Media sources (royalty-free, commercial ok):
- Mixkit Free License — mixkit.co  (default when no Pexels key)
- Pexels License — pexels.com      (used when PEXELS_API_KEY is set)
  Photos provided by Pexels: https://www.pexels.com
Brand kit, clapper slate, rough cut, and host VO are generated locally.
"""


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit(
            "imageio-ffmpeg is required (it's in requirements.txt).\n"
            "  pip install imageio-ffmpeg"
        ) from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:400]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err}")


def _request(url: str, headers: dict[str, str], timeout: int = 120):
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def download(url: str, dest: Path, headers: dict[str, str] | None = None) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    hdrs = dict(headers or UA)
    for attempt in range(1, 4):
        try:
            with _request(url, hdrs) as resp, open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            size = dest.stat().st_size
            if size < 2048:
                raise RuntimeError(f"download too small ({size} B): {url}")
            return size
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            last_err = exc
            if dest.exists():
                dest.unlink()
            time.sleep(attempt)
    raise RuntimeError(f"download failed after retries: {url} ({last_err})")


def mixkit_video_url(video_id: int, height: int = 720) -> str:
    return f"https://assets.mixkit.co/videos/{video_id}/{video_id}-{height}.mp4"


def mixkit_sfx_url(sfx_id: int) -> str:
    return f"https://assets.mixkit.co/active_storage/sfx/{sfx_id}/{sfx_id}.wav"


def mixkit_music_url(music_id: int) -> str:
    return f"https://assets.mixkit.co/music/{music_id}/{music_id}.mp3"


def transcode_video(src: Path, dest: Path, seconds: float, keep_audio: bool) -> None:
    w, h = VIDEO_SIZE
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    )
    args = [
        "-i", str(src),
        "-t", f"{seconds:.2f}",
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "28",
        "-maxrate", "1800k",
        "-bufsize", "3600k",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if keep_audio:
        args += ["-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "44100"]
    else:
        args += ["-an"]
    args.append(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(args)


def extract_still(src: Path, dest: Path, at_sec: float = 2.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-ss", f"{at_sec:.2f}",
        "-i", str(src),
        "-frames:v", "1",
        "-vf", "scale=1280:-2",
        "-q:v", "4",
        str(dest),
    ])


def transcode_audio(src: Path, dest: Path, seconds: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src),
        "-t", f"{seconds:.2f}",
        "-ac", "1",
        "-ar", "22050",
        str(dest),
    ])


def pexels_get(path: str, key: str, params: dict[str, str]) -> dict:
    qs = urllib.parse.urlencode(params)
    url = f"https://api.pexels.com/v1/{path}?{qs}"
    headers = {**UA, "Authorization": key}
    with _request(url, headers, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_pexels_mp4(video: dict) -> str | None:
    files = [
        f for f in (video.get("video_files") or [])
        if f.get("file_type") == "video/mp4" and f.get("link")
        and f.get("width") and f.get("height")
    ]
    landscape = [f for f in files if int(f["width"]) >= int(f["height"])]
    pool = landscape or files
    if not pool:
        return None

    def score(f: dict) -> tuple:
        h = int(f["height"])
        # Prefer 720p; never grab 4K just to throw it away.
        oversize = 1 if h > 1080 else 0
        return (oversize, abs(h - 720), -h)

    pool.sort(key=score)
    return pool[0]["link"]


def pexels_video(key: str, query: str) -> str | None:
    data = pexels_get("videos/search", key, {
        "query": query,
        "orientation": "landscape",
        "per_page": "8",
        "size": "small",
    })
    for video in data.get("videos") or []:
        if int(video.get("duration") or 0) < 4:
            continue
        if int(video.get("width") or 0) < int(video.get("height") or 1):
            continue
        link = pick_pexels_mp4(video)
        if link:
            return link
    return None


def pexels_photo(key: str, query: str) -> str | None:
    data = pexels_get("search", key, {
        "query": query,
        "orientation": "landscape",
        "per_page": "5",
    })
    photos = data.get("photos") or []
    if not photos:
        return None
    src = photos[0].get("src") or {}
    return src.get("large") or src.get("landscape") or src.get("original")


def fetch_mixkit_video(video_id: int, dest: Path) -> int:
    last_err: Exception | None = None
    for height in (720, 360):
        url = mixkit_video_url(video_id, height)
        try:
            return download(url, dest, BROWSER_UA)
        except RuntimeError as exc:
            last_err = exc
    raise RuntimeError(f"Mixkit video {video_id} unavailable ({last_err})")


def generate_keepers() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import make_sample_pack
    from make_media_samples import make_rough_cut, make_voiceover

    print("Generating brand kit, slate, rough cut, host VO…")
    make_sample_pack.main()
    make_rough_cut("video/project_rough_cut_v3.mov")
    print("  wrote video/project_rough_cut_v3.mov")
    make_voiceover("audio/voiceover_host_scene4.wav")
    print("  wrote audio/voiceover_host_scene4.wav")


def clean_legacy() -> None:
    for rel in LEGACY:
        path = ASSETS / rel
        if path.is_file():
            path.unlink()
            print(f"  removed leftover {rel}")


def write_notes() -> None:
    path = ASSETS / "notes.txt"
    path.write_text(NOTES, encoding="utf-8")
    print("  wrote notes.txt")


def fmt_kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):.1f} MB"


def fetch_videos(tmp: Path, pexels_key: str | None) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, mixkit_id in MIXKIT_VIDEOS.items():
        dest = ASSETS / "video" / name
        raw = tmp / name
        source = f"mixkit:{mixkit_id}"
        url: str | None = None
        if pexels_key:
            try:
                url = pexels_video(pexels_key, PEXELS_VIDEO_QUERIES[name])
            except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
                print(f"  ! Pexels miss for {name}: {exc}")
        try:
            if url:
                size = download(url, raw, UA)
                source = "pexels"
            else:
                size = fetch_mixkit_video(mixkit_id, raw)
            print(f"  downloaded {name} ({fmt_kb(size)}, {source})")
            transcode_video(
                raw, dest, VIDEO_SECONDS, keep_audio=name in KEEP_AUDIO,
            )
            print(f"    → {fmt_kb(dest.stat().st_size)} 6s 720p"
                  f"{' +audio' if name in KEEP_AUDIO else ''}")
            out[name] = dest
        except Exception as exc:  # noqa: BLE001 — one miss shouldn't abort the pack
            print(f"  ! skipped {name}: {exc}")
    return out


def fetch_stills(tmp: Path, videos: dict[str, Path], pexels_key: str | None) -> None:
    # Stills pulled from the B-roll we already have (same license, same look).
    from_video = {
        "city_skyline.jpg": "city_skyline_dusk_broll.mp4",
        "product_hero.jpg": "product_hero_macro.mp4",
        "neon_street.jpg": "neon_street_night_broll.mp4",
    }
    for still, video_name in from_video.items():
        dest = ASSETS / "images" / still
        if pexels_key:
            try:
                url = pexels_photo(pexels_key, PEXELS_PHOTO_QUERIES[still])
                if url:
                    download(url, dest, UA)
                    print(f"  photo {still} (pexels, {fmt_kb(dest.stat().st_size)})")
                    continue
            except Exception as exc:  # noqa: BLE001
                print(f"  ! Pexels photo miss for {still}: {exc}")
        src = videos.get(video_name)
        if src and src.is_file():
            extract_still(src, dest, at_sec=2.0)
            print(f"  still {still} from {video_name} ({fmt_kb(dest.stat().st_size)})")
        else:
            print(f"  ! skipped still {still}: no source video")

    # Leftover-from-another-project stills (not in the city-ad cut).
    for still, mixkit_id in MIXKIT_STILL_VIDEOS.items():
        dest = ASSETS / "images" / still
        if pexels_key:
            try:
                url = pexels_photo(pexels_key, PEXELS_PHOTO_QUERIES[still])
                if url:
                    download(url, dest, UA)
                    print(f"  photo {still} (pexels, {fmt_kb(dest.stat().st_size)})")
                    continue
            except Exception as exc:  # noqa: BLE001
                print(f"  ! Pexels photo miss for {still}: {exc}")
        raw = tmp / f"still_{mixkit_id}.mp4"
        try:
            fetch_mixkit_video(mixkit_id, raw)
            extract_still(raw, dest, at_sec=2.0)
            print(f"  still {still} from mixkit:{mixkit_id} ({fmt_kb(dest.stat().st_size)})")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! skipped still {still}: {exc}")


def fetch_audio(tmp: Path) -> None:
    for name, sfx_id in MIXKIT_SFX.items():
        dest = ASSETS / "audio" / name
        raw = tmp / f"{sfx_id}.wav"
        seconds = 1.4 if "whoosh" in name else 4.0
        try:
            size = download(mixkit_sfx_url(sfx_id), raw, BROWSER_UA)
            print(f"  downloaded {name} ({fmt_kb(size)}, mixkit sfx {sfx_id})")
            transcode_audio(raw, dest, seconds)
            print(f"    → {fmt_kb(dest.stat().st_size)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! skipped {name}: {exc}")

    dest = ASSETS / "audio" / "upbeat_bed_8s.wav"
    raw = tmp / "music_644.mp3"
    try:
        size = download(mixkit_music_url(MIXKIT_MUSIC_ID), raw, BROWSER_UA)
        print(f"  downloaded upbeat_bed_8s.wav ({fmt_kb(size)}, mixkit music {MIXKIT_MUSIC_ID})")
        transcode_audio(raw, dest, 8.0)
        print(f"    → {fmt_kb(dest.stat().st_size)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! skipped music bed: {exc}")


def has_audio(path: Path) -> bool:
    proc = subprocess.run(
        [ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True,
    )
    return "Audio:" in (proc.stderr or "")


def mux_ambience_onto_silent_broll() -> None:
    """City B-roll is often published silent. Mix in the city bed so Gemini hears it."""
    video = ASSETS / "video" / "city_skyline_dusk_broll.mp4"
    audio = ASSETS / "audio" / "ambient_city.wav"
    if not video.is_file() or not audio.is_file() or has_audio(video):
        return
    tmp = video.with_suffix(".withaudio.mp4")
    run_ffmpeg([
        "-i", str(video),
        "-stream_loop", "-1",
        "-i", str(audio),
        "-t", f"{VIDEO_SECONDS:.2f}",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "96k",
        "-ac", "1",
        "-shortest",
        "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(video)
    print(f"  muxed ambient_city.wav onto {video.name} (Gemini can hear the bed)")


def copy_duplicates() -> None:
    pairs = [
        ("video/city_skyline_dusk_broll.mp4", "video/city_skyline_dusk_broll_copy.mp4"),
        ("images/city_skyline.jpg", "images/city_skyline_dup.jpg"),
    ]
    for src_rel, dst_rel in pairs:
        src, dst = ASSETS / src_rel, ASSETS / dst_rel
        if src.is_file():
            shutil.copyfile(src, dst)
            print(f"  copied {src_rel} → {dst_rel} (exact duplicate)")


def summarize() -> None:
    print("\nPack in", ASSETS)
    total = 0
    n = 0
    for path in sorted(ASSETS.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        size = path.stat().st_size
        total += size
        n += 1
        print(f"  {path.relative_to(ASSETS)}  {fmt_kb(size)}")
    print(f"{n} files, {fmt_kb(total)} total — Gemini will watch/hear each "
          f"video+audio file under 18 MB.")
    print("\nNext:\n  python scripts/reset_library.py --yes "
          "--ingest sample_assets --project demo --seed 5000")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Fetch a small real Mixkit/Pexels pack and trim it for a cheap Gemini demo.",
    )
    p.add_argument("--pexels-key", default=os.getenv("PEXELS_API_KEY", ""),
                   help="Pexels API key (or set PEXELS_API_KEY). Free at pexels.com/api/")
    p.add_argument("--mixkit-only", action="store_true",
                   help="Skip Pexels even if a key is set.")
    p.add_argument("--skip-generate", action="store_true",
                   help="Do not regenerate the brand kit / slate / rough cut / VO.")
    args = p.parse_args()

    pexels_key = None if args.mixkit_only else (args.pexels_key or "").strip() or None
    if pexels_key:
        print("Source: Pexels (Mixkit fallback per file)")
    else:
        print("Source: Mixkit (no API key). Pass --pexels-key or PEXELS_API_KEY to prefer Pexels.")

    ffmpeg_exe()  # fail fast if the binary is missing
    ASSETS.mkdir(parents=True, exist_ok=True)

    if not args.skip_generate:
        generate_keepers()
    else:
        missing = [
            rel for rel in (
                "brand/logo_primary.png",
                "images/scene12_take3_slate.png",
                "video/project_rough_cut_v3.mov",
                "audio/voiceover_host_scene4.wav",
            )
            if not (ASSETS / rel).is_file()
        ]
        if missing:
            print("Missing generated keepers, running generate anyway:", ", ".join(missing))
            generate_keepers()

    with tempfile.TemporaryDirectory(prefix="xstore-demo-") as tmp_s:
        tmp = Path(tmp_s)
        print("\nFetching + trimming video…")
        videos = fetch_videos(tmp, pexels_key)
        print("\nFetching stills…")
        fetch_stills(tmp, videos, pexels_key)
        print("\nFetching audio…")
        fetch_audio(tmp)

    print("\nDuplicates + cleanup…")
    mux_ambience_onto_silent_broll()
    copy_duplicates()
    clean_legacy()
    write_notes()
    summarize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
