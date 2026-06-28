"""
Spotify dual-mode e-ink display
------------------------------

This combines the live now-playing renderer with the heavy-rotation idle renderer.
- When Spotify is actively playing, the script shows the now-playing layout.
- When playback is paused or idle, it shows the heavy-rotation album grid.
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

ORIENTATION = "landscape"  # "portrait" or "landscape"
FLIP_180 = False
DISPLAY_ROTATION = 270

# Now-playing behavior knobs
IDLE_SECS = 300
POLL_ACTIVE = 5
POLL_IDLE = 60
DEBOUNCE_MS = 3000

# Heavy-rotation idle behavior knobs
TIME_RANGE = "short_term"
TRACK_FETCH_LIMIT = 50
ALBUM_LIMIT = 9
FORCE_REFRESH = "--force" in sys.argv
HEAVY_ROTATION_REFRESH_SECS = 1800

# Spotify auth
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "0fabf53d6f5e4d0ba6a71aaca4e4d64b")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "99db601fe5f2497fbf80f0d67f0b5b03")
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Panel size is detected from the Inky driver after display = auto().
LANDSCAPE_W, LANDSCAPE_H = None, None
BASE_LAYOUT_W, BASE_LAYOUT_H = 600, 448
BASE_ALBUM_ART_SIDE = 408
ALBUM_ART_SIDE = None
_MIN_BOTTOM_BAR_H = None
_MIN_RIGHT_COL_W = None
RIGHT_COL_MARGIN = None
LAYOUT_SCALE = 1.0

# Colors
BG_COLOR = (255, 255, 255)
TASKBAR_BG = (0, 0, 0)
CLOCK_COLOR = (255, 255, 255)
TITLE_COLOR = (0, 0, 0)
ARTIST_COLOR = (0, 0, 0)

# Heavy-rotation colors
HEAVY_BG_COLOR = (255, 255, 255)
HEAVY_TEXT_COLOR = (0, 0, 0)
HEAVY_SUBTEXT_COLOR = (60, 60, 60)
HEAVY_MUTED_COLOR = (95, 95, 95)
HEAVY_DIVIDER_COLOR = (180, 180, 180)

# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Font objects
font_title = font_artist = font_clock = font_header = font_list = None
LINE_TITLE = LINE_ARTIST = LINE_CLOCK = LINE_LIST = BLOCK_SPACING = None

# Heavy-rotation fonts
heavy_font_header = heavy_font_album = heavy_font_artist = heavy_font_top = heavy_font_update = None


def px(value: int) -> int:
    """Scale a layout pixel value to the detected panel size."""
    return max(1, int(round(value * LAYOUT_SCALE)))


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
    scope="user-read-currently-playing user-top-read",
    open_browser=False,
))

display = auto()
PANEL_W, PANEL_H = display.resolution
LAYOUT_SCALE = min(PANEL_W / BASE_LAYOUT_W, PANEL_H / BASE_LAYOUT_H)
LANDSCAPE_W, LANDSCAPE_H = PANEL_W, PANEL_H
ALBUM_ART_SIDE = px(BASE_ALBUM_ART_SIDE)
_MIN_BOTTOM_BAR_H = px(36)
_MIN_RIGHT_COL_W = px(90)
RIGHT_COL_MARGIN = px(12)

font_title = ImageFont.truetype(FONT_BOLD, px(28))
font_artist = ImageFont.truetype(FONT_BOLD, px(28))
font_clock = ImageFont.truetype(FONT_BOLD, px(22))
font_header = ImageFont.truetype(FONT_BOLD, px(18))
font_list = ImageFont.truetype(FONT_REG, px(16))
LINE_TITLE = px(32)
LINE_ARTIST = px(28)
LINE_CLOCK = px(22)
LINE_LIST = px(22)
BLOCK_SPACING = px(10)

heavy_font_header = ImageFont.truetype(FONT_BOLD, 42)
heavy_font_album = ImageFont.truetype(FONT_BOLD, 23)
heavy_font_artist = ImageFont.truetype(FONT_REG, 21)
heavy_font_top = ImageFont.truetype(FONT_REG, 21)
heavy_font_update = ImageFont.truetype(FONT_REG, 20)

# ============================================================
# HELPERS
# ============================================================

def maybe_flip(img: Image.Image) -> Image.Image:
    return img.rotate(180) if FLIP_180 else img


def show_image(img: Image.Image) -> None:
    """Validate image size before sending to the e-ink panel."""
    if img.size != (PANEL_W, PANEL_H):
        raise ValueError(f"Rendered image is {img.size}, expected {(PANEL_W, PANEL_H)}")
    display.set_image(maybe_flip(img))
    display.show()


# ---- Text helpers ----

def truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """Shorten text with ellipsis to fit width."""
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


def wrap_ellipsis(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> List[str]:
    """
    Wrap text into <= max_lines.
    - Long single words are BROKEN across lines (no ellipsis on the word itself).
    - Ellipsis is used ONLY if the overall text exceeds max_lines.
    Returns a list of 0..max_lines strings.
    """
    def split_long_word(word: str) -> List[str]:
        chunks = []
        i = 0
        n = len(word)
        while i < n:
            lo, hi = i + 1, n
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                piece = word[i:mid]
                if draw.textlength(piece, font=font) <= max_w:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is None:
                best = i + 1
            chunks.append(word[i:best])
            i = best
        return chunks

    raw_words = text.split()
    if not raw_words:
        return []

    words = []
    for word in raw_words:
        if draw.textlength(word, font=font) <= max_w:
            words.append(word)
        else:
            words.extend(split_long_word(word))

    lines = []
    cur = ""
    i = 0

    while i < len(words):
        w = words[i]
        trial = w if not cur else (cur + " " + w)

        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            i += 1
            continue

        if cur:
            lines.append(cur)
            cur = ""
        else:
            lines.append(w)
            i += 1

        if len(lines) == max_lines:
            if i < len(words) or cur:
                tail = " ".join(words[i:]) if i < len(words) else ""
                add = (cur + " " + tail).strip()
                lines[-1] = truncate(draw, (lines[-1] + " " + add).strip(), font, max_w)
            return lines

    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = truncate(draw, kept[-1], font, max_w)
        return kept

    return lines


# ---- Time & date helpers ----

def clock_str_round10() -> str:
    """
    Time rounded to nearest 10 minutes.
    Changes at minutes ending in 5 (e.g. 10:05, 10:15, ...).
    """
    tm = time.localtime()
    rounded_min = int(round(tm.tm_min / 10.0) * 10)
    if rounded_min == 60:
        tm_hour = (tm.tm_hour + 1) % 24
        rounded_min = 0
    else:
        tm_hour = tm.tm_hour

    hour_12 = tm_hour % 12
    if hour_12 == 0:
        hour_12 = 12
    ampm = "AM" if tm_hour < 12 else "PM"
    return f"{hour_12}:{rounded_min:02d} {ampm}"


def date_str() -> str:
    """Return date like 'Mon, Nov 24'."""
    return time.strftime("%a, %b %d", time.localtime())


# ============================================================
# NOW-PLAYING RENDERER
# ============================================================

def compute_layout_from_art_side() -> tuple[int, int, int, int]:
    max_side_by_height = LANDSCAPE_H - _MIN_BOTTOM_BAR_H
    max_side_by_width = LANDSCAPE_W - _MIN_RIGHT_COL_W - 2 * RIGHT_COL_MARGIN
    art_side = min(ALBUM_ART_SIDE, max_side_by_height, max_side_by_width)

    bottom_bar_h = LANDSCAPE_H - art_side
    col_x0 = art_side + RIGHT_COL_MARGIN
    col_x1 = LANDSCAPE_W - RIGHT_COL_MARGIN
    right_col_w = max(0, col_x1 - col_x0)

    return art_side, bottom_bar_h, right_col_w, col_x0


def draw_taskbar(draw: ImageDraw.ImageDraw, bottom_bar_h: int, clock_text: str, date_text: str) -> None:
    bar_y0 = LANDSCAPE_H - bottom_bar_h
    draw.line([(0, bar_y0 - 1), (LANDSCAPE_W, bar_y0 - 1)], fill=(220, 220, 220))
    draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)

    sep = " | "
    base_x = px(12)
    clock_h_approx = LINE_CLOCK
    baseline_y = bar_y0 + (bottom_bar_h - clock_h_approx) // 2

    draw.text((base_x, baseline_y), clock_text, font=font_clock, fill=CLOCK_COLOR)
    x = base_x + draw.textlength(clock_text, font=font_clock) + px(6)
    draw.text((x, baseline_y), sep, font=font_clock, fill=CLOCK_COLOR)
    x += draw.textlength(sep, font=font_clock) + px(6)
    draw.text((x, baseline_y), date_text, font=font_clock, fill=CLOCK_COLOR)


def draw_layout_landscape(track: str, artist: str, art_url: str, clock_text: str, date_text: str) -> Image.Image:
    art_side, bottom_bar_h, right_col_w, col_x0 = compute_layout_from_art_side()

    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    art = Image.open(BytesIO(requests.get(art_url, timeout=25).content)).convert("RGB")
    scale = art_side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    left = (new_w - art_side) // 2
    top = (new_h - art_side) // 2
    art = art.crop((left, top, left + art_side, top + art_side))
    img.paste(art, (0, 0))

    col_y0 = 0
    col_y1 = LANDSCAPE_H - bottom_bar_h
    col_w = right_col_w
    if col_w > 0 and col_y1 > col_y0:
        title_lines = wrap_ellipsis(draw, track, font_title, col_w, max_lines=7)
        artist_lines = wrap_ellipsis(draw, artist, font_artist, col_w, max_lines=4)

        cur_y = col_y0 + px(8)
        for ln in title_lines:
            draw.text((col_x0, cur_y), ln, font=font_title, fill=TITLE_COLOR)
            cur_y += LINE_TITLE

        if title_lines and artist_lines:
            sep_y = cur_y + px(4)
            line_w = int(col_w * 0.5)
            line_x0 = col_x0 + (col_w - line_w) // 2
            line_x1 = line_x0 + line_w
            draw.line([(line_x0, sep_y), (line_x1, sep_y)], fill=(60, 60, 60), width=px(2))
            cur_y = sep_y + px(8)
        else:
            cur_y += px(6)

        for ln in artist_lines:
            draw.text((col_x0, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
            cur_y += LINE_ARTIST

    draw_taskbar(draw, bottom_bar_h, clock_text, date_text)
    return img


def draw_now_playing_portrait(track: str, artist: str, art_url: str, clock_text: str, date_text: str) -> Image.Image:
    PORTRAIT_W, PORTRAIT_H = PANEL_H, PANEL_W
    bar_h = max(px(60), _MIN_BOTTOM_BAR_H)

    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    art_side = min(PORTRAIT_W, PORTRAIT_H - bar_h - px(140))
    art = Image.open(BytesIO(requests.get(art_url, timeout=25).content)).convert("RGB")
    scale = art_side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    left = (new_w - art_side) // 2
    top = (new_h - art_side) // 2
    art = art.crop((left, top, left + art_side, top + art_side))
    img.paste(art, ((PORTRAIT_W - art_side) // 2, 0))

    y0 = art_side + px(8)
    margin = px(12)
    max_w = PORTRAIT_W - margin * 2

    title_lines = wrap_ellipsis(draw, track, font_title, max_w, max_lines=5)
    artist_lines = wrap_ellipsis(draw, artist, font_artist, max_w, max_lines=2)

    cur_y = y0 + px(6)
    for ln in title_lines:
        draw.text((margin, cur_y), ln, font=font_title, fill=TITLE_COLOR)
        cur_y += LINE_TITLE

    if title_lines and artist_lines:
        sep_y = cur_y + px(4)
        line_w = int(max_w * 0.5)
        line_x0 = margin + (max_w - line_w) // 2
        line_x1 = line_x0 + line_w
        draw.line([(line_x0, sep_y), (line_x1, sep_y)], fill=(60, 60, 60), width=px(2))
        cur_y = sep_y + px(8)
    else:
        cur_y += px(4)

    for ln in artist_lines:
        draw.text((margin, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
        cur_y += LINE_ARTIST

    bar_y0 = PORTRAIT_H - bar_h
    draw.rectangle([0, bar_y0, PORTRAIT_W, PORTRAIT_H], fill=TASKBAR_BG)
    sep = " | "
    base_x = px(10)
    baseline_y = bar_y0 + (bar_h - LINE_CLOCK) // 2
    draw.text((base_x, baseline_y), clock_text, font=font_clock, fill=CLOCK_COLOR)
    x = base_x + draw.textlength(clock_text, font=font_clock) + px(6)
    draw.text((x, baseline_y), sep, font=font_clock, fill=CLOCK_COLOR)
    x += draw.textlength(sep, font=font_clock) + px(6)
    draw.text((x, baseline_y), date_text, font=font_clock, fill=CLOCK_COLOR)

    return img.rotate(90, expand=True)


def draw_now_playing(track: str, artist: str, art_url: str, clock_text: str, date_text: str) -> None:
    if ORIENTATION == "portrait":
        img = draw_now_playing_portrait(track, artist, art_url, clock_text, date_text)
    else:
        img = draw_layout_landscape(track, artist, art_url, clock_text, date_text)
    show_image(img)


# ============================================================
# HEAVY-ROTATION IDLE RENDERER
# ============================================================

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


def album_artist_name(album: dict, track_artists: list) -> str:
    """Prefer album artist; fall back to track artist."""
    album_artists = album.get("artists", [])
    if album_artists:
        return ", ".join(a["name"] for a in album_artists if a.get("name")) or "Unknown Artist"

    return ", ".join(a["name"] for a in track_artists if a.get("name")) or "Unknown Artist"


_heavy_cache: Dict[str, object] = {"ts": 0.0, "items": None}


def get_heavy_rotation_albums(track_fetch_limit: int = TRACK_FETCH_LIMIT, album_limit: int = ALBUM_LIMIT, time_range: str = TIME_RANGE) -> List[dict]:
    now = time.monotonic()
    if (not FORCE_REFRESH) and _heavy_cache["items"] and ((now - _heavy_cache["ts"]) < (TOP_CACHE_TTL if "TOP_CACHE_TTL" in globals() else 21600)):
        return _heavy_cache["items"]

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
    albums.sort(key=lambda a: (-a["score"], a["top_track_rank"], a["album_name"].lower()))
    selected = albums[:album_limit]

    for idx, album in enumerate(selected, start=1):
        album["rank"] = idx

    _heavy_cache["items"] = selected
    _heavy_cache["ts"] = now
    return selected


def draw_heavy_rotation_idle(clock_text: str, date_text: str) -> None:
    """Render the heavy-rotation album grid as the standby screen."""
    CANVAS_W = 1200
    CANVAS_H = 1600
    OUTER_MARGIN = 0
    GRID_GAP = 0
    GRID_COLS = 3
    GRID_ROWS = 3
    GRID_TILE = (CANVAS_W - 2 * OUTER_MARGIN - (GRID_COLS - 1) * GRID_GAP) // GRID_COLS
    GRID_TOP = OUTER_MARGIN
    GRID_HEIGHT = GRID_ROWS * GRID_TILE + (GRID_ROWS - 1) * GRID_GAP
    FOOTER_TOP = GRID_TOP + GRID_HEIGHT
    FOOTER_H = CANVAS_H - FOOTER_TOP

    albums = get_heavy_rotation_albums()
    if not albums:
        return

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), HEAVY_BG_COLOR)
    draw = ImageDraw.Draw(img)

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
            tw = art_draw.textlength(placeholder, font=heavy_font_album)
            art_draw.text(((GRID_TILE - tw) / 2, GRID_TILE / 2 - 14), placeholder, font=heavy_font_album, fill=HEAVY_TEXT_COLOR)

        img.paste(art, (x, y))

    y0 = FOOTER_TOP
    draw.line([(0, y0), (CANVAS_W, y0)], fill=HEAVY_DIVIDER_COLOR, width=2)

    title_y = y0 + 14
    draw.text((24, title_y), "HEAVY ROTATION", font=heavy_font_header, fill=HEAVY_TEXT_COLOR)
    subtitle = "albums from recent top tracks"
    subtitle_x = 24 + int(draw.textlength("HEAVY ROTATION", font=heavy_font_header)) + 18
    subtitle_y = title_y + 14
    draw.text((subtitle_x, subtitle_y), subtitle, font=heavy_font_top, fill=HEAVY_MUTED_COLOR)

    content_top = title_y + 62
    col_gap = 18
    side_pad = 24
    col_w = (CANVAS_W - 2 * side_pad - 2 * col_gap) // 3
    block_h = 96

    for row in range(3):
        base_y = content_top + row * block_h
        for col in range(3):
            idx = row * 3 + col
            if idx >= len(albums):
                continue
            item = albums[idx]
            col_x = side_pad + col * (col_w + col_gap)
            album_line = truncate(draw, f"{item['rank']}. {item['album_name']}", heavy_font_album, col_w)
            artist_line = truncate(draw, item["artist"], heavy_font_artist, col_w)
            top_line = truncate(draw, f"top: {item['top_track']}", heavy_font_top, col_w)
            draw.text((col_x, base_y), album_line, font=heavy_font_album, fill=HEAVY_TEXT_COLOR)
            draw.text((col_x, base_y + 29), artist_line, font=heavy_font_artist, fill=HEAVY_SUBTEXT_COLOR)
            draw.text((col_x, base_y + 56), top_line, font=heavy_font_top, fill=HEAVY_MUTED_COLOR)

    updated = time.strftime("Updated %a, %b %d at %I:%M %p", time.localtime()).replace(" 0", " ")
    draw.text((24, CANVAS_H - 32), updated, font=heavy_font_update, fill=HEAVY_MUTED_COLOR)

    display_img = img.rotate(DISPLAY_ROTATION, expand=True)
    display_img = maybe_flip(display_img)
    if display_img.size != display.resolution:
        raise RuntimeError(f"Final image size {display_img.size} does not match display resolution {display.resolution}.")

    display.set_image(display_img)
    display.show()


# ============================================================
# MAIN LOOP
# ============================================================

last_track_id = None
last_active_ts = time.monotonic()
idle_shown = False
candidate_id = None
candidate_first_seen = 0.0
last_idle_draw_ts = 0.0

print(f"[Init] Panel {PANEL_W}x{PANEL_H} | orientation={ORIENTATION} | scale={LAYOUT_SCALE:.2f} | ALBUM_ART_SIDE={ALBUM_ART_SIDE}")

while True:
    sleep_s = POLL_ACTIVE
    try:
        current_clock = clock_str_round10()
        current_date = date_str()

        current = sp.current_user_playing_track()
        if current and current.get("is_playing") and current.get("item"):
            tid = current["item"]["id"]
            track = current["item"]["name"]
            artist = ", ".join(a["name"] for a in current["item"].get("artists", []) if a.get("name"))
            arturl = current["item"]["album"]["images"][0]["url"]
            prog = current.get("progress_ms") or 0

            now = time.monotonic()
            last_active_ts = now

            if candidate_id != tid:
                candidate_id = tid
                candidate_first_seen = now - (prog / 1000.0)

            listened_ms = (now - candidate_first_seen) * 1000.0
            should_redraw = False
            if listened_ms >= DEBOUNCE_MS:
                if tid != last_track_id or idle_shown:
                    should_redraw = True

            if should_redraw:
                print(f"Now playing: {track} – {artist} | {current_clock} {current_date}")
                draw_now_playing(track, artist, arturl, current_clock, current_date)
                last_track_id = tid
                idle_shown = False

            sleep_s = POLL_ACTIVE

        else:
            now = time.monotonic()
            idle_for = now - last_active_ts
            if (not idle_shown) or ((now - last_idle_draw_ts) >= HEAVY_ROTATION_REFRESH_SECS):
                print(f"Idle mode: heavy rotation | {current_clock} {current_date}")
                draw_heavy_rotation_idle(current_clock, current_date)
                idle_shown = True
                last_idle_draw_ts = now

            sleep_s = POLL_IDLE if idle_for >= IDLE_SECS else POLL_ACTIVE

    except spotipy.SpotifyException as e:
        if getattr(e, "http_status", None) == 429:
            retry_after = int(getattr(e, "headers", {}).get("Retry-After", 10))
            print(f"429 rate-limited. Backing off {retry_after}s")
            sleep_s = max(sleep_s, retry_after)
        else:
            print("[SpotifyException]", e)
            sleep_s = max(sleep_s, 60)
    except Exception as e:
        print("[ERROR]", e)
        sleep_s = max(sleep_s, 60)

    time.sleep(sleep_s)
