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

# Panel size
LANDSCAPE_W, LANDSCAPE_H = 600, 448

# Single master control: desired album art side length (in pixels)
ALBUM_ART_SIDE = 420  # change this one number to grow/shrink art; bars adapt automatically

# Internal minimums so layout doesn't collapse
_MIN_BOTTOM_BAR_H = 40
_MIN_RIGHT_COL_W  = 90
RIGHT_COL_MARGIN  = 12

# Colors
BG_COLOR    = (255, 255, 255)
TASKBAR_BG  = (0, 0, 0)
CLOCK_COLOR = (255, 255, 255)
TITLE_COLOR = (0, 0, 0)
ARTIST_COLOR = (60, 60, 60)

# Fonts
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
PANEL_W, PANEL_H = display.resolution  # e.g. 600x448

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
    i = 0
    while i < len(words):
        w = words[i]
        trial = w if not cur else (cur + " " + w)
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            i += 1
        else:
            if cur:
                lines.append(cur)
            else:
                # a single too-long word: hard truncate that word
                lines.append(truncate(draw, w, font, max_w))
                i += 1
            cur = ""
        if len(lines) == max_lines:
            # Already at max lines; append remainder with ellipsis
            if i < len(words):
                tail = " ".join(words[i:])
                lines[-1] = truncate(draw, lines[-1] + " " + tail, font, max_w)
            return lines

    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate(draw, lines[-1], font, max_w)
    return lines

# ---- Clock (rounded down to nearest 10 minutes) ----
def clock_str_round10():
    tm = time.localtime()
    rounded_min = (tm.tm_min // 10) * 10
    hour = tm.tm_hour % 12
    if hour == 0:
        hour = 12
    return f"{hour:01d}:{rounded_min:02d} {'AM' if tm.tm_hour < 12 else 'PM'}"

# ---- Layout computation from single art-size variable ----
def compute_layout_from_art_side():
    """
    Given ALBUM_ART_SIDE, compute:
      - art_side: actual square album-art side that fits screen + minimums
      - bottom_bar_h: remaining vertical space (taskbar height)
      - right_col_w: remaining horizontal space (side info column)
      - col_x0: left x of right column
    """
    # Start with desired side, clamp so that:
    #   art_side + _MIN_BOTTOM_BAR_H <= panel height
    #   art_side + _MIN_RIGHT_COL_W + 2*margin <= panel width
    max_side_by_height = LANDSCAPE_H - _MIN_BOTTOM_BAR_H
    max_side_by_width  = LANDSCAPE_W - _MIN_RIGHT_COL_W - 2*RIGHT_COL_MARGIN
    art_side = min(ALBUM_ART_SIDE, max_side_by_height, max_side_by_width)

    # Now derive bar height & right column width from leftover space
    bottom_bar_h = LANDSCAPE_H - art_side
    col_x0 = art_side + RIGHT_COL_MARGIN
    col_x1 = LANDSCAPE_W - RIGHT_COL_MARGIN
    right_col_w = max(0, col_x1 - col_x0)

    return art_side, bottom_bar_h, right_col_w, col_x0

# ---- Landscape main layout ----
def draw_layout_landscape(track, artist, art_url, clock_text):
    """
    Layout in landscape:
      - Square album art at (0,0) with side 'art_side' derived from ALBUM_ART_SIDE.
      - Right column (auto width) for track & artist, wrapped.
      - Bottom taskbar (auto height) with clock on the right.
    """
    art_side, bottom_bar_h, right_col_w, col_x0 = compute_layout_from_art_side()

    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- Album art as square of size art_side ---
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    # scale so shorter side == art_side, then center-crop
    scale = art_side / min(art.width, art.height)
    new_w = int(art.width * scale)
    new_h = int(art.height * scale)
    art = art.resize((new_w, new_h))
    left = (new_w - art_side) // 2
    top  = (new_h - art_side) // 2
    art = art.crop((left, top, left + art_side, top + art_side))
    img.paste(art, (0, 0))

    # --- Right column (above taskbar) ---
    col_y0 = 0
    col_y1 = LANDSCAPE_H - bottom_bar_h
    col_w  = right_col_w
    if col_w > 0 and col_y1 > col_y0:
        title_lines  = wrap_ellipsis(draw, track,  font_title,  col_w, max_lines=3)
        artist_lines = wrap_ellipsis(draw, artist, font_artist, col_w, max_lines=2)

        cur_y = col_y0 + 8
        for ln in title_lines:
            draw.text((col_x0, cur_y), ln, font=font_title, fill=TITLE_COLOR)
            cur_y += 30
        cur_y += 6
        for ln in artist_lines:
            draw.text((col_x0, cur_y), ln, font=font_artist, fill=ARTIST_COLOR)
            cur_y += 24

    # --- Divider & taskbar ---
    bar_y0 = LANDSCAPE_H - bottom_bar_h
    draw.line([(0, bar_y0 - 1), (LANDSCAPE_W, bar_y0 - 1)], fill=(220,220,220))
    draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)

    # Clock centered vertically in bar
    clock_w = draw.textlength(clock_text, font=font_clock)
    clock_h_approx = 28
    clock_x = LANDSCAPE_W - clock_w - 12
    clock_y = bar_y0 + (bottom_bar_h - clock_h_approx)//2
    draw.text((clock_x, clock_y), clock_text, font=font_clock, fill=CLOCK_COLOR)

    return img

# ---- Portrait fallback ----
def draw_now_playing_portrait(track, artist, art_url, clock_text):
    PORTRAIT_W, PORTRAIT_H = 448, 600
    bar_h = 72

    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((448, 448))
    img.paste(art, (0, 0))

    y0 = 448
    margin = 12
    max_w = PORTRAIT_W - margin*2
    track_draw  = truncate(draw, track,  font_title,  max_w)
    artist_draw = truncate(draw, artist, font_artist, max_w)
    draw.text((margin, y0 + 6), track_draw,  font=font_title,  fill=TITLE_COLOR)
    draw.text((margin, y0 + 40), artist_draw, font=font_artist, fill=ARTIST_COLOR)

    bar_y0 = PORTRAIT_H - bar_h
    draw.rectangle([0, bar_y0, PORTRAIT_W, PORTRAIT_H], fill=TASKBAR_BG)
    clock_w = draw.textlength(clock_text, font=font_clock)
    clock_h_approx = 28
    draw.text(
        (PORTRAIT_W - clock_w - 10, bar_y0 + (bar_h - clock_h_approx)//2),
        clock_text,
        font=font_clock,
        fill=CLOCK_COLOR
    )

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
    if top_items:
        hero = top_items[0]
        track = "Top this week"
        artist = f"{len(top_items)} tracks"
        art_url = hero["img"]
        draw_now_playing(track, artist, art_url, clock_text)
    else:
        # Just show empty background + clock taskbar
        _, bottom_bar_h, _, _ = compute_layout_from_art_side()
        img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), BG_COLOR)
        draw = ImageDraw.Draw(img)
        bar_y0 = LANDSCAPE_H - bottom_bar_h
        draw.rectangle([0, bar_y0, LANDSCAPE_W, LANDSCAPE_H], fill=TASKBAR_BG)
        clock_w = draw.textlength(clock_text, font=font_clock)
        clock_h_approx = 28
        draw.text(
            (LANDSCAPE_W - clock_w - 12, bar_y0 + (bottom_bar_h - clock_h_approx)//2),
            clock_text,
            font=font_clock,
            fill=CLOCK_COLOR
        )
        display.set_image(maybe_flip(img))
        display.show()

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
last_clock_str     = None

print(f"[Init] Panel {PANEL_W}x{PANEL_H} | orientation={ORIENTATION} | ALBUM_ART_SIDE={ALBUM_ART_SIDE}")

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
                    should_redraw = True

            if should_redraw:
                print(f"Now playing: {track} – {artist} | {current_clock}")
                draw_now_playing(track, artist, arturl, current_clock)
                last_track_id = tid
                idle_shown = False
                last_clock_str = current_clock

            sleep_s = POLL_ACTIVE

        else:
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
                if clock_changed:
                    top_items = get_top_tracks(limit=7, time_range="short_term")
                    draw_idle_top_list(top_items, current_clock)
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
