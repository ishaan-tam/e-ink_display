import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageStat
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from inky.auto import auto

# === USER SETTINGS ===
ORIENTATION   = "landscape"   # "portrait" or "landscape"
FLIP_180      = False         # True if image appears upside down

# Sizes/colors
LANDSCAPE_W, LANDSCAPE_H = 600, 448
BOTTOM_BAR_H = 50                # taskbar height
RIGHT_COL_MARGIN = 12            # gap between art and right column
BG_COLOR = (255, 255, 255)       # main background
TASKBAR_BG = (0, 0, 0)           # taskbar background
CLOCK_COLOR = (255, 255, 255)    # clock text color
TITLE_COLOR = (0, 0, 0)          # title text in right column
ARTIST_COLOR = (60, 60, 60)      # artist text in right column

# Fonts (adjust sizes/paths if needed)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title   = ImageFont.truetype(FONT_BOLD, 28)
font_artist  = ImageFont.truetype(FONT_REG, 20)
font_clock   = ImageFont.truetype(FONT_BOLD, 28)
font_header  = ImageFont.truetype(FONT_BOLD, 18)
font_list    = ImageFont.truetype(FONT_REG, 16)

# ---- Behavior knobs ----
IDLE_SECS     = 600
POLL_ACTIVE   = 5
POLL_IDLE     = 60
DEBOUNCE_MS   = 3000
TOP_CACHE_TTL = 21600

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
PANEL_W, PANEL_H = display.resolution  # e.g., 600x448 on Inky Impression 5.7

# ---- Orientation handling ----
def maybe_flip(img):
    return img.rotate(180) if FLIP_180 else img

# ---- Text helpers ----
def truncate(draw, text, font, max_w):
    """Shorten text with ellipsis to fit width"""
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
    Greedy wrap into at most max_lines, with ellipsis on the last line if needed.
    Returns a list of 0..max_lines strings.
    """
    words = text.split()
    if not words:
        return []

    lines = []
    cur = ""
    for w in words:
        trial = w if not cur else (cur + " " + w)
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            else:
                # single long word: hard cut
                lines.append(truncate(draw, w, font, max_w))
            cur = w
        if len(lines) == max_lines:
            # already full, need to ellipsize last
            lines[-1] = truncate(draw, lines[-1] + " " + " ".join(words[words.index(w):]), font, max_w)
            return lines
    if cur:
        lines.append(cur)

    # if too many, ellipsize the last
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate(draw, lines[-1], font, max_w)
    return lines

# ---- Clock (rounded to nearest lower 10 minutes) ----
def clock_str_round10():
    tm = time.localtime()
    rounded_min = (tm.tm_min // 10) * 10
    # 12-hour taskbar-like format: "10:30 AM"
    hour = tm.tm_hour % 12
    if hour == 0:
        hour = 12
    return f"{hour:01d}:{rounded_min:02d} {'AM' if tm.tm_hour < 12 else 'PM'}"

# ---- Core draw: landscape with big square art, right info column, bottom taskbar with clock ----
def draw_layout_landscape(track, artist, art_url, clock_text):
    """
    Layout:
    - Big square album art at left, sized to (LANDSCAPE_H - BOTTOM_BAR_H).
    - Right column for title/artist, wrapped to fit.
    - Bottom taskbar spans full width with clock at right.
    """
    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Compute art size (square) to fit height above the taskbar
    art_size = LANDSCAPE_H - BOTTOM_BAR_H  # e.g., 376px with 72px bar
    # Fetch & resize art, preserving aspect, then crop/letterbox to square
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    # Fit so smallest side == art_size, then center-crop to square
    scale = art_size / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    # center-crop to square art_size x art_size
    left = (new_w - art_size) // 2
    top  = (new_h - art_size) // 2
    art = art.crop((left, top, left + art_size, top + art_size))

    # Paste art at left/top
    art_x, art_y = 0, 0
    img.paste(art, (art_x, art_y))

    # Right column bounds (above taskbar)
    col_x0 = art_x + art_size + RIGHT_COL_MARGIN
    col_y0 = 0
    col_x1 = LANDSCAPE_W - RIGHT_COL_MARGIN
    col_y1 = LANDSCAPE_H - BOTTOM_BAR_H
    col_w  = max(0, col_x1 - col_x0)

    # Draw track + artist wrapped into the column
    if col_w > 0:
        title_lines  = wrap_ellipsis(draw, track,  font_title,  col_w, max_lines=3)
        artist_lines = wrap_ellipsis(draw, artist, font_artist, col_w, max_lines=2)

        cur_y = col_y0 + 8
        for ln in title_lines:
            draw.text((col_x0, cur_y), ln, font=font_title, fill=TITLE_COLOR)
            cur_y += 30  # line spacing for title
        cur_y += 6
        for ln in artist_lines:
            draw.text((col_x0, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
            cur_y += 24

    # (Optional) subtle divider above taskbar
    draw.line([(0, LANDSCAPE_H - BOTTOM_BAR_H - 1), (LANDSCAPE_W, LANDSCAPE_H - BOTTOM_BAR_H - 1)], fill=(220,220,220))

    # Taskbar background
    bar_y0 = LANDSCAPE_H - BOTTOM_BAR_H
    draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)

    # Clock at right of taskbar
    clock_w = draw.textlength(clock_text, font=font_clock)
    clock_h = 28  # approximate height of font_clock
    draw.text(
        (LANDSCAPE_W - clock_w - 12, bar_y0 + (BOTTOM_BAR_H - clock_h)//2),
        clock_text,
        font=font_clock,
        fill=CLOCK_COLOR
    )       

    return img

# ---- Portrait fallback (kept minimal) ----
def draw_now_playing_portrait(track, artist, art_url, clock_text):
    PORTRAIT_W, PORTRAIT_H = 448, 600
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((448, 448))
    img.paste(art, (0, 0))

    # bottom taskbar
    bar_h = 72
    bar_y0 = PORTRAIT_H - bar_h
    draw.rectangle([0, bar_y0, PORTRAIT_W, PORTRAIT_H], fill=TASKBAR_BG)

    # text area (above bar)
    y0 = 448
    margin = 12
    max_w = PORTRAIT_W - margin*2
    track_draw  = truncate(draw, track,  font_title,  max_w)
    artist_draw = truncate(draw, artist, font_artist, max_w)
    draw.text((margin, y0 + 6), track_draw,  font=font_title,  fill=TITLE_COLOR)
    draw.text((margin, y0 + 40), artist_draw, font=font_artist, fill=ARTIST_COLOR)

    # clock right-aligned in bar
    clock_w = draw.textlength(clock_text, font=font_clock)
    draw.text((PORTRAIT_W - clock_w - 10, bar_y0 + (bar_h - 28)//2), clock_text, font=font_clock, fill=CLOCK_COLOR)

    # rotate to panel
    img = img.rotate(90, expand=True)
    return img

# ---- Public draw entrypoints ----
def draw_now_playing(track, artist, art_url, clock_text):
    if ORIENTATION == "portrait":
        img = draw_now_playing_portrait(track, artist, art_url, clock_text)
    else:
        img = draw_layout_landscape(track, artist, art_url, clock_text)
    display.set_image(maybe_flip(img))
    display.show()

def draw_idle_top_list(top_items, clock_text):
    # Simple idle: reuse layout with hero art + "Top this week" as title
    if top_items:
        hero = top_items[0]
        track = "Top this week"
        artist = f"{len(top_items)} tracks"
        art_url = hero["img"]
    else:
        track = "Nothing playing"
        artist = "—"
        art_url = "https://via.placeholder.com/512"  # fallback (won't be fetched if nothing)

    # If no items, draw a blank canvas with just taskbar/clock
    if not top_items:
        img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
        draw = ImageDraw.Draw(img)
        # bar
        bar_y0 = LANDSCAPE_H - BOTTOM_BAR_H
        draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)
        clock_w = draw.textlength(clock_text, font=font_clock)
        draw.text((LANDSCAPE_W - clock_w - 12, bar_y0 + (BOTTOM_BAR_H - 28)//2), clock_text, font=font_clock, fill=CLOCK_COLOR)
        display.set_image(maybe_flip(img))
        display.show()
    else:
        draw_now_playing(track, artist, art_url, clock_text)

# ---- Top tracks cache ----
_top_cache = {"ts": 0, "items": None}
def get_top_tracks(limit=7, time_range="short_term"):
    now = time.monotonic()
    if not _top_cache["items"] or (now - _top_cache["ts"]) > TOP_CACHE_TTL:
        items = sp.current_user_top_tracks(limit=limit, time_range=time_range).get("items", [])
        _top_cache["items"] = [{
            "id": it["id"],
            "name": it["name"],
            "artist": it["artists"][0]["name"],
            "img": it["album"]["images"][0]["url"]
        } for it in items]
        _top_cache["ts"] = now
    return _top_cache["items"]

# ---- Main loop ----
last_track_id      = None
last_active_ts     = time.monotonic()
idle_shown         = False
candidate_id       = None
candidate_first_seen = 0.0
last_clock_str     = None  # to avoid needless refreshes

print(f"[Init] Panel {PANEL_W}x{PANEL_H} | orientation={ORIENTATION}")

while True:
    sleep_s = POLL_ACTIVE
    try:
        current_clock = clock_str_round10()
        clock_changed = (current_clock != last_clock_str)

        current = sp.current_user_playing_track()
        if current and current.get("is_playing") and current.get("item"):
            tid    = current["item"]["id"]
            track  = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
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
                elif clock_changed:
                    # Only clock changed → refresh taskbar
                    should_redraw = True

            if should_redraw:
                print(f"Now playing: {track} – {artist} | {current_clock}")
                draw_now_playing(track, artist, arturl, current_clock)
                last_track_id = tid
                idle_shown = False
                last_clock_str = current_clock

            sleep_s = POLL_ACTIVE

        else:
            # Idle
            idle_for = time.monotonic() - last_active_ts
            if idle_for >= IDLE_SECS:
                if clock_changed or not idle_shown:
                    top_items = get_top_tracks(limit=7, time_range="short_term")
                    print(f"Idle mode | {current_clock}")
                    draw_idle_top_list(top_items, current_clock)
                    idle_shown = True
                    last_clock_str = current_clock
                sleep_s = POLL_IDLE
            else:
                # Not yet idle; still update the clock if it ticked to a new 10-min mark
                if clock_changed:
                    top_items = get_top_tracks(limit=7, time_range="short_term")
                    draw_idle_top_list(top_items, current_clock)  # lightweight refresh
                    last_clock_str = current_clock
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
