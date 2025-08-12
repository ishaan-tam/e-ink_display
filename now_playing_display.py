import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from inky.auto import auto

# === ENTER YOUR SPOTIFY CREDENTIALS ===
CLIENT_ID = "0fabf53d6f5e4d0ba6a71aaca4e4d64b"
CLIENT_SECRET = "99db601fe5f2497fbf80f0d67f0b5b03"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
# =======================================

# ---- Layout (portrait compose -> rotate to panel) ----
PORTRAIT_W, PORTRAIT_H = 448, 600
TOP_ART_SIZE = 448
ROTATE_DEG = 90  # use -90 if orientation appears flipped

# Fonts (adjust sizes/paths if needed)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title  = ImageFont.truetype(FONT_BOLD, 28)
font_artist = ImageFont.truetype(FONT_REG, 22)
font_header = ImageFont.truetype(FONT_BOLD, 18)
font_list   = ImageFont.truetype(FONT_REG, 16)

# ---- Behavior knobs ----
IDLE_SECS     = 600   # 10 minutes to switch to top-tracks mode
POLL_ACTIVE   = 5     # poll every 5s while playing
POLL_IDLE     = 60    # poll every 60s while idle
DEBOUNCE_MS   = 3000  # require 3s listened time before updating a new track
TOP_CACHE_TTL = 21600 # 6h cache for top tracks to prevent churn (24h = 86400)

# ---- Spotify + Inky init ----
scope = "user-read-currently-playing user-top-read"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

display = auto()  # auto-detect Inky panel
PANEL_W, PANEL_H = display.resolution  # 600 x 448 on Inky Impression 5.7

# ---------------- helpers ----------------
def truncate(draw, text, font, max_w):
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

def paste_rotated(img_portrait):
    # Flip everything (art + text) by 180° on top of your base rotation
    rotated = img_portrait.rotate((ROTATE_DEG + 180) % 360, expand=True)  # -> 600x448
    display.set_image(rotated)
    display.show()

def draw_now_playing(track, artist, art_url):
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    # album art
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))

    # bottom text band
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    max_w = PORTRAIT_W - margin*2
    track_draw  = truncate(draw, track,  font_title,  max_w)
    artist_draw = truncate(draw, artist, font_artist, max_w)
    draw.text((margin, y0 + 10), track_draw,  font=font_title,  fill=(255,255,255))
    draw.text((margin, y0 + 48), artist_draw, font=font_artist, fill=(230,230,230))

    paste_rotated(img)

# ---- Top tracks with caching/signature ----
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

def top_signature(top_items):
    return tuple(t["id"] for t in top_items) if top_items else None

def draw_idle_top_list(top_items, include_hero_in_list=True):
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    if not top_items:
        msg = "No top tracks available"
        w = int(draw.textlength(msg, font=font_header))
        draw.text(((PORTRAIT_W - w)//2, PORTRAIT_H//2 - 10), msg, font=font_header, fill=(0,0,0))
        paste_rotated(img)
        return

    # hero art (top1)
    hero = top_items[0]
    art = Image.open(BytesIO(requests.get(hero["img"]).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))

    # bottom band
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    draw.text((margin, y0 + 8), "Top this week", font=font_header, fill=(255,255,255))

    list_y = y0 + 8 + 24
    line_h = 22
    max_w = PORTRAIT_W - margin*2 - 18
    listing = top_items if include_hero_in_list else top_items[1:]
    max_lines = (PORTRAIT_H - list_y) // line_h
    for i, t in enumerate(listing[:max_lines]):
        line = f"{t['name']} — {t['artist']}"
        line = truncate(draw, line, font_list, max_w)
        draw.text((margin, list_y + i*line_h), "•", font=font_list, fill=(220,220,220))
        draw.text((margin + 14, list_y + i*line_h), line, font=font_list, fill=(230,230,230))

    paste_rotated(img)

# ---------------- main loop ----------------
last_track_id   = None           # last rendered track
last_active_ts  = time.monotonic()
idle_shown      = False
last_idle_sig   = None

# debounce state
candidate_id         = None
candidate_first_seen = 0.0

while True:
    sleep_s = POLL_ACTIVE
    try:
        current = sp.current_user_playing_track()

        if current and current.get("is_playing") and current.get("item"):
            # --- playing ---
            tid    = current["item"]["id"]
            track  = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            arturl = current["item"]["album"]["images"][0]["url"]
            prog   = current.get("progress_ms") or 0

            now = time.monotonic()
            last_active_ts = now

            # debounce: require ≥ DEBOUNCE_MS listened time for a new track
            if candidate_id != tid:
                candidate_id = tid
                candidate_first_seen = now - (prog / 1000.0)  # anchor to start of track via progress_ms

            listened_ms = (now - candidate_first_seen) * 1000.0
            if listened_ms >= DEBOUNCE_MS:
                if tid != last_track_id or idle_shown:
                    print(f"Now playing (debounced): {track} – {artist}")
                    draw_now_playing(track, artist, arturl)
                    last_track_id = tid
                    idle_shown = False

            sleep_s = POLL_ACTIVE

        else:
            # --- idle / paused ---
            idle_for = time.monotonic() - last_active_ts
            if idle_for >= IDLE_SECS:
                # Poll top tracks (cached) and compute signature; redraw ONLY if changed or first idle
                top_items = get_top_tracks(limit=7, time_range="short_term")
                sig = top_signature(top_items)
                if (not idle_shown) or (sig != last_idle_sig):
                    print("Idle mode: top tracks changed (or first idle) → redraw")
                    draw_idle_top_list(top_items, include_hero_in_list=True)
                    last_idle_sig = sig
                    idle_shown = True
                else:
                    print("Idle mode: no change → no redraw")
                sleep_s = POLL_IDLE
            else:
                sleep_s = POLL_ACTIVE

    except spotipy.SpotifyException as e:
        # Handle rate-limit gracefully
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