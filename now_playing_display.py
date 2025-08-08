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

# ---- Layout settings (portrait composition, rotate to panel) ----
PORTRAIT_W, PORTRAIT_H = 448, 600
ROTATE_DEG = 90             # use -90 if orientation is wrong on your panel
TOP_ART_SIZE = 448          # now-playing art or top-1 art size
TEXT_H = PORTRAIT_H - TOP_ART_SIZE  # 152 px band
# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title  = ImageFont.truetype(FONT_BOLD, 28)
font_artist = ImageFont.truetype(FONT_REG, 22)
font_header = ImageFont.truetype(FONT_BOLD, 18)
font_list   = ImageFont.truetype(FONT_REG, 16)

# ---- Behaviour knobs ----
IDLE_SECS = 600            # 10 minutes to switch to top-tracks mode
POLL_ACTIVE = 15           # when playing, check every 15s
POLL_IDLE   = 60           # when idle, check every 60s
TOP_CACHE_TTL = 3600       # refresh top tracks at most once per hour
IDLE_REDRAW_GAP = 300      # don’t redraw idle screen more often than every 5 minutes

# ---- Spotify + Inky init ----
scope = "user-read-currently-playing user-top-read"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

display = auto()
PANEL_W, PANEL_H = display.resolution  # 600 x 448 on Inky Impression 5.7

# ---- Helpers ----
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
    rotated = img_portrait.rotate(ROTATE_DEG, expand=True)  # -> 600x448
    display.set_image(rotated)
    display.show()

def draw_now_playing(track, artist, art_url):
    # Base portrait
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)
    # Art
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))
    # Text band
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    max_w = PORTRAIT_W - margin*2
    track_draw  = truncate(draw, track,  font_title,  max_w)
    artist_draw = truncate(draw, artist, font_artist, max_w)
    draw.text((margin, y0 + 10), track_draw,  font=font_title,  fill=(255,255,255))
    draw.text((margin, y0 + 48), artist_draw, font=font_artist, fill=(230,230,230))
    paste_rotated(img)

_top_cache = {"ts": 0, "items": None}
def get_top_tracks(limit=7, time_range="short_term"):
    now = time.monotonic()
    if not _top_cache["items"] or (now - _top_cache["ts"]) > TOP_CACHE_TTL:
        items = sp.current_user_top_tracks(limit=limit, time_range=time_range).get("items", [])
        _top_cache["items"] = [{
            "name": it["name"],
            "artist": it["artists"][0]["name"],
            "img": it["album"]["images"][0]["url"]
        } for it in items]
        _top_cache["ts"] = now
    return _top_cache["items"]

def draw_idle_top_list(include_hero_in_list=True):
    top = get_top_tracks(limit=7, time_range="short_term")  # last ~4 weeks
    if not top:
        img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
        draw = ImageDraw.Draw(img)
        msg = "No top tracks available"
        w = int(draw.textlength(msg, font=font_header))
        draw.text(((PORTRAIT_W - w)//2, PORTRAIT_H//2 - 10), msg, font=font_header, fill=(0,0,0))
        paste_rotated(img)
        return

    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    # Hero art (top1)
    hero = top[0]
    art = Image.open(BytesIO(requests.get(hero["img"]).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))

    # Bottom band
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    draw.text((margin, y0 + 8), "Top this week", font=font_header, fill=(255,255,255))

    list_y = y0 + 8 + 24
    line_h = 22
    max_w = PORTRAIT_W - margin*2 - 18
    listing = top if include_hero_in_list else top[1:]
    max_lines = (PORTRAIT_H - list_y) // line_h
    for i, t in enumerate(listing[:max_lines]):
        line = f"{t['name']} — {t['artist']}"
        line = truncate(draw, line, font_list, max_w)
        draw.text((margin, list_y + i*line_h), "•", font=font_list, fill=(220,220,220))
        draw.text((margin + 14, list_y + i*line_h), line, font=font_list, fill=(230,230,230))

    paste_rotated(img)

# ---- Main loop ----
last_track_id = None
last_active_ts = time.monotonic()
idle_last_draw = 0
idle_shown = False

while True:
    sleep_s = POLL_ACTIVE
    try:
        current = sp.current_user_playing_track()
        if current and current.get("is_playing") and current.get("item"):
            # Active playback
            track_id = current["item"]["id"]
            track = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            album_art_url = current["item"]["album"]["images"][0]["url"]

            if track_id != last_track_id or idle_shown:
                print(f"Now playing: {track} – {artist}")
                draw_now_playing(track, artist, album_art_url)
                last_track_id = track_id
                idle_shown = False

            last_active_ts = time.monotonic()
            sleep_s = POLL_ACTIVE

        else:
            # Idle / paused
            idle_for = time.monotonic() - last_active_ts
            if idle_for >= IDLE_SECS:
                if not idle_shown or (time.monotonic() - idle_last_draw) >= IDLE_REDRAW_GAP:
                    print("Idle mode: showing top tracks")
                    draw_idle_top_list(include_hero_in_list=True)
                    idle_last_draw = time.monotonic()
                    idle_shown = True
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
