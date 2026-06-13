"""
Spotify Weekly Top Tracks Grid for Pimoroni Inky Impression 13.3"

- Designed for the 13.3" Inky Impression / Spectra 6 display (1600x1200).
- Renders a portrait layout internally at 1200x1600, then rotates for display.
- Shows a clean 3x3 grid of album art at the top.
- Uses the bottom bar for track text only.
- Intended to run once per day (for example via systemd timer or cron).
- Saves preview PNGs before updating the panel.
"""

import os
import sys
import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from inky.auto import auto

# ============================================================
# USER SETTINGS
# ============================================================
FLIP_180 = False               # True if the final image appears upside down
DISPLAY_ROTATION = 270         # 90 or 270 depending on how your display is mounted
TRACK_LIMIT = 9
TIME_RANGE = "short_term"     # Spotify short_term ~= recent listening / weekly-ish
FORCE_REFRESH = "--force" in sys.argv

# Portrait design canvas; this gets rotated to fit the 1600x1200 panel
CANVAS_W = 1200
CANVAS_H = 1600

# Grid layout
OUTER_MARGIN = 0
GRID_GAP = 0
GRID_COLS = 3
GRID_ROWS = 3
GRID_TILE = (CANVAS_W - 2 * OUTER_MARGIN - (GRID_COLS - 1) * GRID_GAP) // GRID_COLS  # 384 px
GRID_TOP = OUTER_MARGIN
GRID_HEIGHT = GRID_ROWS * GRID_TILE + (GRID_ROWS - 1) * GRID_GAP
FOOTER_TOP = GRID_TOP + GRID_HEIGHT + OUTER_MARGIN
FOOTER_H = CANVAS_H - FOOTER_TOP

# Output files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREVIEW_PORTRAIT_PATH = os.path.join(SCRIPT_DIR, "last_render_portrait.png")
PREVIEW_DISPLAY_PATH = os.path.join(SCRIPT_DIR, "last_render_display.png")
STAMP_PATH = os.path.join(SCRIPT_DIR, ".last_weekly_grid_refresh")

# Colors
BG_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 0, 0)
SUBTEXT_COLOR = (60, 60, 60)
DIVIDER_COLOR = (180, 180, 180)

# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

font_header = ImageFont.truetype(FONT_BOLD, 44)
font_song = ImageFont.truetype(FONT_BOLD, 24)
font_artist = ImageFont.truetype(FONT_REG, 22)
font_update = ImageFont.truetype(FONT_REG, 22)

# ============================================================
# SPOTIFY SETUP
# ============================================================
scope = "user-top-read"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id="0fabf53d6f5e4d0ba6a71aaca4e4d64b",
    client_secret="99db601fe5f2497fbf80f0d67f0b5b03",
    redirect_uri="http://127.0.0.1:8888/callback",
    scope=scope,
    open_browser=False,
))

# ============================================================
# DISPLAY INIT
# ============================================================
display = auto()
PANEL_W, PANEL_H = display.resolution


def maybe_flip(img: Image.Image) -> Image.Image:
    return img.rotate(180) if FLIP_180 else img


# ============================================================
# HELPERS
# ============================================================
def truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
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
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    art = Image.open(BytesIO(resp.content)).convert("RGB")

    scale = side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))

    left = (new_w - side) // 2
    top = (new_h - side) // 2
    art = art.crop((left, top, left + side, top + side))
    return art


def get_top_tracks(limit: int = 9, time_range: str = "short_term"):
    items = sp.current_user_top_tracks(limit=limit, time_range=time_range).get("items", [])
    tracks = []
    for idx, item in enumerate(items[:limit], start=1):
        artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
        images = item.get("album", {}).get("images", [])
        image_url = images[0]["url"] if images else None
        tracks.append({
            "rank": idx,
            "id": item.get("id"),
            "name": item.get("name", "Unknown Track"),
            "artist": artists or "Unknown Artist",
            "img": image_url,
        })
    return tracks


def now_stamp() -> str:
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


# ============================================================
# RENDERING
# ============================================================
def draw_footer(draw: ImageDraw.ImageDraw, top_tracks):
    y0 = FOOTER_TOP

    # Divider line at top of footer
    draw.line([(OUTER_MARGIN, y0), (CANVAS_W - OUTER_MARGIN, y0)], fill=DIVIDER_COLOR, width=2)

    title_y = y0 + 18
    draw.text((OUTER_MARGIN, title_y), "TOP SONGS THIS WEEK", font=font_header, fill=TEXT_COLOR)

    content_top = title_y + 58
    col_gap = 24
    col_w = (CANVAS_W - 2 * OUTER_MARGIN - 2 * col_gap) // 3
    block_h = 88

    # Match the album-art grid order visually:
    # Row 1: 1 2 3
    # Row 2: 4 5 6
    # Row 3: 7 8 9
    for row in range(3):
        base_y = content_top + row * block_h
        for col in range(3):
            idx = row * 3 + col
            if idx >= len(top_tracks):
                continue

            item = top_tracks[idx]
            col_x = OUTER_MARGIN + col * (col_w + col_gap)

            song_text = truncate(draw, f"{item['rank']}. {item['name']}", font_song, col_w)
            artist_text = truncate(draw, item["artist"], font_artist, col_w)

            draw.text((col_x, base_y), song_text, font=font_song, fill=TEXT_COLOR)
            draw.text((col_x, base_y + 32), artist_text, font=font_artist, fill=SUBTEXT_COLOR)

    updated = time.strftime("Updated %a, %b %d at %I:%M %p", time.localtime())
    updated = updated.replace(" 0", " ")
    update_y = CANVAS_H - 34 - 22
    draw.text((OUTER_MARGIN, update_y), updated, font=font_update, fill=SUBTEXT_COLOR)


def render_top_grid(top_tracks):
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Top 3x3 album-art grid
    for idx, item in enumerate(top_tracks[:GRID_COLS * GRID_ROWS]):
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
            tw = art_draw.textlength(placeholder, font=font_song)
            art_draw.text(((GRID_TILE - tw) / 2, GRID_TILE / 2 - 12), placeholder, font=font_song, fill=TEXT_COLOR)

        img.paste(art, (x, y))

    draw_footer(draw, top_tracks)
    return img


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"[Init] Detected panel: {PANEL_W}x{PANEL_H}")
    print(f"[Init] Portrait canvas: {CANVAS_W}x{CANVAS_H} | tile={GRID_TILE}px | footer={FOOTER_H}px")

    if (PANEL_W, PANEL_H) != (1600, 1200):
        print(f"[Warn] Expected 1600x1200 display, but detected {PANEL_W}x{PANEL_H}. Continuing anyway.")

    today = now_stamp()
    last_stamp = read_last_stamp()
    if (not FORCE_REFRESH) and last_stamp == today:
        print(f"[Skip] Already refreshed today ({today}). Use --force to refresh anyway.")
        return

    top_tracks = get_top_tracks(limit=TRACK_LIMIT, time_range=TIME_RANGE)
    if not top_tracks:
        raise RuntimeError("No top tracks returned from Spotify.")

    print(f"[Spotify] Fetched {len(top_tracks)} top tracks.")

    portrait_img = render_top_grid(top_tracks)
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