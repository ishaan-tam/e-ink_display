"""
Spotify Heavy Rotation Album Grid for Pimoroni Inky Impression 13.3"

Layout:
- 13.3" Inky / Spectra 6 panel: 1600x1200
- Internal portrait canvas: 1200x1600
- Top: 3x3 full-width album-art grid, no gaps
- Bottom: "HEAVY ROTATION" footer with album, artist, and representative top song
- Data: top unique albums derived/scored from recent Spotify top tracks
- Intended to run once per day, or manually with --force
"""

import os
import sys
import time
from io import BytesIO
from typing import Dict, List

import requests
import spotipy
from PIL import Image, ImageDraw, ImageFont
from spotipy.oauth2 import SpotifyOAuth
from inky.auto import auto


# ============================================================
# USER SETTINGS
# ============================================================

FLIP_180 = False
DISPLAY_ROTATION = 270          # Change to 90 if the layout is sideways the wrong way

TIME_RANGE = "short_term"       # "short_term", "medium_term", or "long_term"
TRACK_FETCH_LIMIT = 50          # Pull more tracks so album grouping has enough data
ALBUM_LIMIT = 9                 # 3x3 grid
FORCE_REFRESH = "--force" in sys.argv

# Spotify auth.
# Best practice: put your secret in an environment variable instead of hardcoding it.
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "0fabf53d6f5e4d0ba6a71aaca4e4d64b")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "99db601fe5f2497fbf80f0d67f0b5b03")
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Portrait design canvas; this gets rotated to fit the 1600x1200 panel.
CANVAS_W = 1200
CANVAS_H = 1600

# Album grid: true 3x3 mosaic
OUTER_MARGIN = 0
GRID_GAP = 0
GRID_COLS = 3
GRID_ROWS = 3
GRID_TILE = (CANVAS_W - 2 * OUTER_MARGIN - (GRID_COLS - 1) * GRID_GAP) // GRID_COLS  # 400 px
GRID_TOP = OUTER_MARGIN
GRID_HEIGHT = GRID_ROWS * GRID_TILE + (GRID_ROWS - 1) * GRID_GAP
FOOTER_TOP = GRID_TOP + GRID_HEIGHT
FOOTER_H = CANVAS_H - FOOTER_TOP

# Output files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREVIEW_PORTRAIT_PATH = os.path.join(SCRIPT_DIR, "last_render_portrait.png")
PREVIEW_DISPLAY_PATH = os.path.join(SCRIPT_DIR, "last_render_display.png")
STAMP_PATH = os.path.join(SCRIPT_DIR, ".last_heavy_rotation_refresh")

# Colors
BG_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 0, 0)
SUBTEXT_COLOR = (60, 60, 60)
MUTED_COLOR = (95, 95, 95)
DIVIDER_COLOR = (180, 180, 180)

# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

font_header = ImageFont.truetype(FONT_BOLD, 42)
font_album = ImageFont.truetype(FONT_BOLD, 23)
font_artist = ImageFont.truetype(FONT_REG, 21)
font_top = ImageFont.truetype(FONT_REG, 21)      # Same size as artist line for readability
font_update = ImageFont.truetype(FONT_REG, 20)


# ============================================================
# SPOTIFY + DISPLAY INIT
# ============================================================

if SPOTIFY_CLIENT_SECRET == "PASTE_YOUR_CLIENT_SECRET_HERE":
    raise RuntimeError(
        "Set SPOTIFY_CLIENT_SECRET first, or paste your existing Spotify client secret "
        "into SPOTIFY_CLIENT_SECRET near the top of this file."
    )

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope="user-top-read",
    open_browser=False,
))

display = auto()
PANEL_W, PANEL_H = display.resolution


# ============================================================
# HELPERS
# ============================================================

def maybe_flip(img: Image.Image) -> Image.Image:
    return img.rotate(180) if FLIP_180 else img


def truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """Shorten text with ellipsis so it fits in max_w."""
    if draw.textlength(text, font=font) <= max_w:
        return text

    ell = "…"
    lo, hi = 0, len(text)

    while lo < hi:
        mid = (lo + hi) // 2
        trial = text[:mid] + ell
        if draw.textlength(trial, font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid

    return text[:max(0, lo - 1)] + ell


def download_square_album_art(url: str, side: int) -> Image.Image:
    """Download album art, center-crop it square, and resize to side x side."""
    resp = requests.get(url, timeout=25)
    resp.raise_for_status()

    art = Image.open(BytesIO(resp.content)).convert("RGB")
    scale = side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)

    art = art.resize((new_w, new_h))

    left = (new_w - side) // 2
    top = (new_h - side) // 2

    return art.crop((left, top, left + side, top + side))


def today_stamp() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def read_last_stamp() -> str:
    if not os.path.exists(STAMP_PATH):
        return ""

    try:
        with open(STAMP_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def write_stamp(stamp: str):
    with open(STAMP_PATH, "w", encoding="utf-8") as f:
        f.write(stamp)


def album_artist_name(album: dict, track_artists: list) -> str:
    """Prefer album artist; fall back to track artist."""
    album_artists = album.get("artists", [])
    if album_artists:
        return ", ".join(a["name"] for a in album_artists if a.get("name")) or "Unknown Artist"

    return ", ".join(a["name"] for a in track_artists if a.get("name")) or "Unknown Artist"


# ============================================================
# SPOTIFY DATA: TOP ALBUMS DERIVED FROM TOP TRACKS
# ============================================================

def get_heavy_rotation_albums(
    track_fetch_limit: int = TRACK_FETCH_LIMIT,
    album_limit: int = ALBUM_LIMIT,
    time_range: str = TIME_RANGE,
) -> List[dict]:
    """
    Fetch recent top tracks and group them into unique albums.

    Scoring:
    - Track rank 1 gets track_fetch_limit points.
    - Track rank 2 gets track_fetch_limit - 1 points.
    - Track rank 50 gets 1 point when TRACK_FETCH_LIMIT = 50.
    - Multiple tracks from the same album add together.
    - Representative top song = highest-ranked song from that album.

    Example with TRACK_FETCH_LIMIT = 50:
    - Rank 2 song from Currents: 49 points
    - Rank 8 song from Currents: 43 points
    - Rank 20 song from Currents: 31 points
    - Currents total score: 123
    """
    response = sp.current_user_top_tracks(limit=track_fetch_limit, time_range=time_range)
    tracks = response.get("items", [])

    grouped: Dict[str, dict] = {}

    for rank, track in enumerate(tracks, start=1):
        album = track.get("album", {})
        album_id = album.get("id") or album.get("name") or f"unknown-{rank}"

        album_name = album.get("name") or "Unknown Album"
        artist_name = album_artist_name(album, track.get("artists", []))

        images = album.get("images", [])
        image_url = images[0]["url"] if images else None

        track_name = track.get("name") or "Unknown Track"
        points = track_fetch_limit - rank + 1

        if album_id not in grouped:
            grouped[album_id] = {
                "album_id": album_id,
                "album_name": album_name,
                "artist": artist_name,
                "img": image_url,
                "score": 0,
                "track_count": 0,
                "top_track": track_name,
                "top_track_rank": rank,
            }

        grouped_album = grouped[album_id]
        grouped_album["score"] += points
        grouped_album["track_count"] += 1

        if rank < grouped_album["top_track_rank"]:
            grouped_album["top_track"] = track_name
            grouped_album["top_track_rank"] = rank

    albums = list(grouped.values())

    albums.sort(
        key=lambda a: (
            -a["score"],
            a["top_track_rank"],
            a["album_name"].lower(),
        )
    )

    selected = albums[:album_limit]

    for idx, album in enumerate(selected, start=1):
        album["rank"] = idx

    return selected


# ============================================================
# RENDERING
# ============================================================

def draw_footer(draw: ImageDraw.ImageDraw, albums: List[dict]):
    """
    Bottom footer:
    - Header: HEAVY ROTATION
    - 3x3 text map matching album art:
        1 2 3
        4 5 6
        7 8 9
    - Each item:
        Album
        Artist
        top: Representative Song
    """
    y0 = FOOTER_TOP

    # Thin divider separating art and text
    draw.line([(0, y0), (CANVAS_W, y0)], fill=DIVIDER_COLOR, width=2)

    title_y = y0 + 14
    draw.text((24, title_y), "HEAVY ROTATION", font=font_header, fill=TEXT_COLOR)

    subtitle = "albums from recent top tracks"
    subtitle_x = 24 + int(draw.textlength("HEAVY ROTATION", font=font_header)) + 18
    subtitle_y = title_y + 14
    draw.text((subtitle_x, subtitle_y), subtitle, font=font_top, fill=MUTED_COLOR)

    content_top = title_y + 62

    col_gap = 18
    side_pad = 24
    col_w = (CANVAS_W - 2 * side_pad - 2 * col_gap) // 3
    block_h = 96

    # Match album-art visual order:
    # Row 1: 1 2 3
    # Row 2: 4 5 6
    # Row 3: 7 8 9
    for row in range(3):
        base_y = content_top + row * block_h

        for col in range(3):
            idx = row * 3 + col
            if idx >= len(albums):
                continue

            item = albums[idx]
            col_x = side_pad + col * (col_w + col_gap)

            album_line = truncate(draw, f"{item['rank']}. {item['album_name']}", font_album, col_w)
            artist_line = truncate(draw, item["artist"], font_artist, col_w)
            top_line = truncate(draw, f"top: {item['top_track']}", font_top, col_w)

            draw.text((col_x, base_y), album_line, font=font_album, fill=TEXT_COLOR)
            draw.text((col_x, base_y + 29), artist_line, font=font_artist, fill=SUBTEXT_COLOR)
            draw.text((col_x, base_y + 56), top_line, font=font_top, fill=MUTED_COLOR)

    updated = time.strftime("Updated %a, %b %d at %I:%M %p", time.localtime()).replace(" 0", " ")
    draw.text((24, CANVAS_H - 32), updated, font=font_update, fill=MUTED_COLOR)


def render_album_grid(albums: List[dict]) -> Image.Image:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Top 3x3 album-art grid
    for idx, item in enumerate(albums[:GRID_COLS * GRID_ROWS]):
        row = idx // GRID_COLS
        col = idx % GRID_COLS

        x = OUTER_MARGIN + col * (GRID_TILE + GRID_GAP)
        y = GRID_TOP + row * (GRID_TILE + GRID_GAP)

        if item.get("img"):
            art = download_square_album_art(item["img"], GRID_TILE)
        else:
            art = Image.new("RGB", (GRID_TILE, GRID_TILE), (230, 230, 230))
            art_draw = ImageDraw.Draw(art)
            placeholder = "No Art"
            tw = art_draw.textlength(placeholder, font=font_album)
            art_draw.text(((GRID_TILE - tw) / 2, GRID_TILE / 2 - 14), placeholder, font=font_album, fill=TEXT_COLOR)

        img.paste(art, (x, y))

    draw_footer(draw, albums)
    return img


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"[Init] Detected panel: {PANEL_W}x{PANEL_H}")
    print(f"[Init] Canvas: {CANVAS_W}x{CANVAS_H} | grid tile={GRID_TILE}px | footer={FOOTER_H}px")

    if (PANEL_W, PANEL_H) != (1600, 1200):
        print(f"[Warn] Expected 1600x1200 display, but detected {PANEL_W}x{PANEL_H}. Continuing anyway.")

    today = today_stamp()
    last_stamp = read_last_stamp()

    if (not FORCE_REFRESH) and last_stamp == today:
        print(f"[Skip] Already refreshed today ({today}). Use --force to refresh anyway.")
        return

    albums = get_heavy_rotation_albums(
        track_fetch_limit=TRACK_FETCH_LIMIT,
        album_limit=ALBUM_LIMIT,
        time_range=TIME_RANGE,
    )

    if not albums:
        raise RuntimeError("No albums returned from Spotify top tracks.")

    print(f"[Spotify] Built {len(albums)} heavy-rotation albums from top {TRACK_FETCH_LIMIT} tracks.")

    for a in albums:
        print(
            f"  {a['rank']}. {a['album_name']} — {a['artist']} "
            f"(top: {a['top_track']}, score={a['score']}, tracks={a['track_count']})"
        )

    portrait_img = render_album_grid(albums)
    portrait_img.save(PREVIEW_PORTRAIT_PATH)
    print(f"[Preview] Saved portrait preview: {PREVIEW_PORTRAIT_PATH}")

    display_img = portrait_img.rotate(DISPLAY_ROTATION, expand=True)
    display_img = maybe_flip(display_img)
    display_img.save(PREVIEW_DISPLAY_PATH)
    print(f"[Preview] Saved display preview:  {PREVIEW_DISPLAY_PATH}")

    if display_img.size != display.resolution:
        raise RuntimeError(
            f"Final image size {display_img.size} does not match display resolution {display.resolution}. "
            f"Try DISPLAY_ROTATION=90 or 270."
        )

    print("[Display] Updating e-ink panel...")
    display.set_image(display_img)
    display.show()

    write_stamp(today)
    print("[Done] Refresh complete.")


if __name__ == "__main__":
    try:
        main()
    except spotipy.SpotifyException as e:
        print("[SpotifyException]", e)
        raise
    except Exception as e:
        print("[ERROR]", e)
        raise
