"""
Spotify E-Ink Display (Landscape/Portrait Adaptive)
---------------------------------------------------

FEATURES
--------
• Shows the currently playing Spotify track:
    - Large album art
    - Multi-line song title + artist
    - Can toggle between portrait/landscape modes
    - Clock + date with nearest-10-minute rounding
    - Only refreshes the screen when necessary to preserve e-ink life

• Idle Mode (after 10 minutes of inactivity):
    - Hero image = top track’s album art
    - “Top this week” header (multi-line)
    - Top 5 tracks displayed as:
        * Song title (bold, up to 2 lines)
        * Artist line (regular)
        * Vertical spacing (clean, no numbering)
    - Standby refresh capped to once every 30 minutes

• Layout System:
    - All dimensions derived from a single ALBUM_ART_SIDE variable
    - Bottom taskbar auto-sizes
    - Right-column wrapping + truncation logic

• Behavior / Performance:
    - Debounces track changes (≥3s listened time)
    - Polling frequency reduces when paused
    - Top-track API results cached for 6 hours
    - Avoids unnecessary re-renders to extend panel lifespan

• Service-Friendly:
    - Designed to run under systemd as “spotify-display.service”
    - No command-line arguments needed
    - Orientation and behavior adjustable inside code

FUTURE-PROOFING / EXTENSIBILITY
-------------------------------
• QR-based Spotify login (no need to manually enter client secrets)
• Weather, stocks, and widgets for the taskbar or idle pages
• NFC-triggered actions: share photos, pair devices, load playlists
• Web dashboard for settings (font size, themes, orientation)
• Multiple idle screens (auto-rotating dashboards)
• Integration with HomeKit, MQTT, or custom REST APIs
"""

import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from inky.auto import auto

# === USER SETTINGS ===
ORIENTATION   = "landscape"   # "portrait" or "landscape"
FLIP_180      = False         # True if image appears upside down

# Panel size
LANDSCAPE_W, LANDSCAPE_H = 600, 448

# Single master control: desired album art side length (in pixels)
# Slightly larger so the bottom bar is smaller (~40px).
ALBUM_ART_SIDE = 408

# Internal minimums so layout doesn't collapse
_MIN_BOTTOM_BAR_H = 36
_MIN_RIGHT_COL_W  = 90
RIGHT_COL_MARGIN  = 12

# Colors
BG_COLOR     = (255, 255, 255)
TASKBAR_BG   = (0, 0, 0)
CLOCK_COLOR  = (255, 255, 255)
TITLE_COLOR  = (0, 0, 0)
ARTIST_COLOR = (0, 0, 0)   # high-contrast artist text

# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

font_title   = ImageFont.truetype(FONT_BOLD, 28)
font_artist  = ImageFont.truetype(FONT_BOLD, 28)  # same boldness/size as title
font_clock   = ImageFont.truetype(FONT_BOLD, 22)  # smaller for taskbar
font_header  = ImageFont.truetype(FONT_BOLD, 18)
font_list    = ImageFont.truetype(FONT_REG, 16)

# ---- Behavior knobs ----
IDLE_SECS         = 300    # seconds of no playback before entering standby
POLL_ACTIVE       = 5
POLL_IDLE         = 60
DEBOUNCE_MS       = 3000
TOP_CACHE_TTL     = 21600  # cache top tracks for 6h
IDLE_REFRESH_SECS = 1800   # refresh standby screen at most every 30 min

# ---- Spotify + Inky init ----
scope = "user-read-currently-playing user-top-read"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id="0fabf53d6f5e4d0ba6a71aaca4e4d64b",
    client_secret="99db601fe5f2497fbf80f0d67f0b5b03",
    redirect_uri="http://127.0.0.1:8888/callback",
    scope=scope,
    open_browser=False
))

display = auto()
PANEL_W, PANEL_H = display.resolution  # e.g. 600x448

# ---- Orientation handling ----
def maybe_flip(img):
    return img.rotate(180) if FLIP_180 else img

# ---- Text helpers ----
def truncate(draw, text, font, max_w):
    """Shorten text with ellipsis to fit width."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi)//2
        trial = text[:mid] + ell
        if draw.textlength(trial, font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return text[:max(0, lo-1)] + ell

def wrap_ellipsis(draw, text, font, max_w, max_lines):
    """
    Wrap text into <= max_lines.
    - Long single words are BROKEN across lines (no ellipsis on the word itself).
    - Ellipsis is used ONLY if the overall text exceeds max_lines.
    Returns a list of 0..max_lines strings.
    """
    def split_long_word(word: str):
        """Split a single too-long word into chunks that each fit max_w."""
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

    # Expand long words into chunks that fit
    words = []
    for w in raw_words:
        if draw.textlength(w, font=font) <= max_w:
            words.append(w)
        else:
            words.extend(split_long_word(w))

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

        # trial didn't fit
        if cur:
            lines.append(cur)
            cur = ""
        else:
            # extremely rare fallback
            lines.append(w)
            i += 1

        if len(lines) == max_lines:
            # out of lines: ellipsize last line if there's remaining content
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
def clock_str_round10():
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

def date_str():
    """Return date like 'Mon, Nov 24'."""
    return time.strftime("%a, %b %d", time.localtime())

# ---- Layout computation from single art-size variable ----
def compute_layout_from_art_side():
    max_side_by_height = LANDSCAPE_H - _MIN_BOTTOM_BAR_H
    max_side_by_width  = LANDSCAPE_W - _MIN_RIGHT_COL_W - 2*RIGHT_COL_MARGIN
    art_side = min(ALBUM_ART_SIDE, max_side_by_height, max_side_by_width)

    bottom_bar_h = LANDSCAPE_H - art_side
    col_x0 = art_side + RIGHT_COL_MARGIN
    col_x1 = LANDSCAPE_W - RIGHT_COL_MARGIN
    right_col_w = max(0, col_x1 - col_x0)

    return art_side, bottom_bar_h, right_col_w, col_x0

# ---- Shared taskbar drawing ----
def draw_taskbar(draw, bottom_bar_h, clock_text, date_text):
    bar_y0 = LANDSCAPE_H - bottom_bar_h
    draw.line([(0, bar_y0 - 1), (LANDSCAPE_W, bar_y0 - 1)], fill=(220,220,220))
    draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)

    sep = " | "
    base_x = 12
    clock_h_approx = 22
    baseline_y = bar_y0 + (bottom_bar_h - clock_h_approx)//2

    draw.text((base_x, baseline_y), clock_text, font=font_clock, fill=CLOCK_COLOR)
    x = base_x + draw.textlength(clock_text, font=font_clock) + 6
    draw.text((x, baseline_y), sep, font=font_clock, fill=CLOCK_COLOR)
    x += draw.textlength(sep, font=font_clock) + 6
    draw.text((x, baseline_y), date_text, font=font_clock, fill=CLOCK_COLOR)

# ---- Landscape now-playing layout ----
def draw_layout_landscape(track, artist, art_url, clock_text, date_text):
    art_side, bottom_bar_h, right_col_w, col_x0 = compute_layout_from_art_side()

    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Album art
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    scale = art_side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    left = (new_w - art_side) // 2
    top  = (new_h - art_side) // 2
    art = art.crop((left, top, left + art_side, top + art_side))
    img.paste(art, (0, 0))

    # Right column
    col_y0 = 0
    col_y1 = LANDSCAPE_H - bottom_bar_h
    col_w  = right_col_w
    if col_w > 0 and col_y1 > col_y0:
        title_lines  = wrap_ellipsis(draw, track,  font_title,  col_w, max_lines=7)
        artist_lines = wrap_ellipsis(draw, artist, font_artist, col_w, max_lines=4)

        cur_y = col_y0 + 8
        for ln in title_lines:
            draw.text((col_x0, cur_y), ln, font=font_title, fill=TITLE_COLOR)
            cur_y += 32

        # separator line
        if title_lines and artist_lines:
            sep_y = cur_y + 4
            line_w = int(col_w * 0.5)
            line_x0 = col_x0 + (col_w - line_w)//2
            line_x1 = line_x0 + line_w
            draw.line([(line_x0, sep_y), (line_x1, sep_y)], fill=(60, 60, 60), width=2)
            cur_y = sep_y + 8
        else:
            cur_y += 6

        for ln in artist_lines:
            draw.text((col_x0, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
            cur_y += 28

    draw_taskbar(draw, bottom_bar_h, clock_text, date_text)
    return img

# ---- Portrait fallback ----
def draw_now_playing_portrait(track, artist, art_url, clock_text, date_text):
    PORTRAIT_W, PORTRAIT_H = 448, 600
    bar_h = 60

    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((448, 448))
    img.paste(art, (0, 0))

    y0 = 448
    margin = 12
    max_w = PORTRAIT_W - margin*2

    title_lines  = wrap_ellipsis(draw, track,  font_title,  max_w, max_lines=5)
    artist_lines = wrap_ellipsis(draw, artist, font_artist, max_w, max_lines=2)

    cur_y = y0 + 6
    for ln in title_lines:
        draw.text((margin, cur_y), ln, font=font_title, fill=TITLE_COLOR)
        cur_y += 32

    if title_lines and artist_lines:
        sep_y = cur_y + 4
        line_w = int(max_w * 0.5)
        line_x0 = margin + (max_w - line_w)//2
        line_x1 = line_x0 + line_w
        draw.line([(line_x0, sep_y), (line_x1, sep_y)], fill=(60, 60, 60), width=2)
        cur_y = sep_y + 8
    else:
        cur_y += 4

    for ln in artist_lines:
        draw.text((margin, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
        cur_y += 28

    # taskbar
    bar_y0 = PORTRAIT_H - bar_h
    draw.rectangle([0, bar_y0, PORTRAIT_W, PORTRAIT_H], fill=TASKBAR_BG)
    sep = " | "
    base_x = 10
    baseline_y = bar_y0 + (bar_h - 22)//2
    draw.text((base_x, baseline_y), clock_text, font=font_clock, fill=CLOCK_COLOR)
    x = base_x + draw.textlength(clock_text, font=font_clock) + 6
    draw.text((x, baseline_y), sep, font=font_clock, fill=CLOCK_COLOR)
    x += draw.textlength(sep, font=font_clock) + 6
    draw.text((x, baseline_y), date_text, font=font_clock, fill=CLOCK_COLOR)

    img = img.rotate(90, expand=True)
    return img

# ---- Public draw entrypoints ----
def draw_now_playing(track, artist, art_url, clock_text, date_text):
    if ORIENTATION == "portrait":
        img = draw_now_playing_portrait(track, artist, art_url, clock_text, date_text)
    else:
        img = draw_layout_landscape(track, artist, art_url, clock_text, date_text)
    display.set_image(maybe_flip(img))
    display.show()

# ---- Idle / standby: hero + top tracks list ----
_top_cache = {"ts": 0, "items": None}

def get_top_tracks(limit=7, time_range="short_term"):
    now = time.monotonic()
    if (not _top_cache["items"]) or ((now - _top_cache["ts"]) > TOP_CACHE_TTL):
        items = sp.current_user_top_tracks(limit=limit, time_range=time_range).get("items", [])
        _top_cache["items"] = [{
            "id": it["id"],
            "name": it["name"],
            "artist": ", ".join(a["name"] for a in it.get("artists", []) if a.get("name")),  # MULTI-ARTIST
            "img": it["album"]["images"][0]["url"]
        } for it in items]
        _top_cache["ts"] = now
    return _top_cache["items"]

def draw_idle_top_list(top_items, clock_text, date_text):
    art_side, bottom_bar_h, right_col_w, col_x0 = compute_layout_from_art_side()
    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    if not top_items:
        draw_taskbar(draw, bottom_bar_h, clock_text, date_text)
        display.set_image(maybe_flip(img))
        display.show()
        return

    # hero art
    hero = top_items[0]
    art_url = hero["img"]
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    scale = art_side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    left = (new_w - art_side) // 2
    top = (new_h - art_side) // 2
    art = art.crop((left, top, left + art_side, top + art_side))
    img.paste(art, (0, 0))

    # right column list
    col_y0 = 0
    col_y1 = LANDSCAPE_H - bottom_bar_h
    col_w  = right_col_w
    if col_w > 0 and col_y1 > col_y0:
        y = col_y0 + 8

        heading_lines = wrap_ellipsis(draw, "Top this week", font_title, col_w, max_lines=2)
        for ln in heading_lines:
            draw.text((col_x0, y), ln, font=font_title, fill=TITLE_COLOR)
            y += 32
        y += 8

        title_line_h   = 30
        artist_line_h  = 22
        block_spacing  = 10

        for t in top_items[:5]:
            song   = t["name"]
            artist = t["artist"]

            song_lines = wrap_ellipsis(draw, song, font_title, col_w, max_lines=2)
            artist_text = truncate(draw, artist, font_list, col_w)

            needed_h = title_line_h * len(song_lines) + artist_line_h + block_spacing
            if y + needed_h > col_y1:
                break

            for ln in song_lines:
                draw.text((col_x0, y), ln, font=font_title, fill=TITLE_COLOR)
                y += title_line_h

            draw.text((col_x0, y), artist_text, font=font_list, fill=ARTIST_COLOR)
            y += artist_line_h + block_spacing

    draw_taskbar(draw, bottom_bar_h, clock_text, date_text)
    display.set_image(maybe_flip(img))
    display.show()

# ---- Main loop ----
last_track_id        = None
last_active_ts       = time.monotonic()
idle_shown           = False
candidate_id         = None
candidate_first_seen = 0.0
last_idle_draw_ts    = 0.0

print(f"[Init] Panel {PANEL_W}x{PANEL_H} | orientation={ORIENTATION} | ALBUM_ART_SIDE={ALBUM_ART_SIDE}")

while True:
    sleep_s = POLL_ACTIVE
    try:
        current_clock = clock_str_round10()
        current_date  = date_str()

        current = sp.current_user_playing_track()
        if current and current.get("is_playing") and current.get("item"):
            tid    = current["item"]["id"]
            track  = current["item"]["name"]
            artist = ", ".join(a["name"] for a in current["item"].get("artists", []) if a.get("name"))  # MULTI-ARTIST
            arturl = current["item"]["album"]["images"][0]["url"]
            prog   = current.get("progress_ms") or 0

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
            if idle_for >= IDLE_SECS:
                if (not idle_shown) or ((now - last_idle_draw_ts) >= IDLE_REFRESH_SECS):
                    top_items = get_top_tracks(limit=7, time_range="short_term")
                    print(f"Idle mode: top tracks | {current_clock} {current_date}")
                    draw_idle_top_list(top_items, current_clock, current_date)
                    idle_shown = True
                    last_idle_draw_ts = now
                sleep_s = POLL_IDLE
            else:
                sleep_s = POLL_ACTIVE

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
