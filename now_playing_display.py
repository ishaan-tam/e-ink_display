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
# ======================

# === ENTER YOUR SPOTIFY CREDENTIALS ===
CLIENT_ID = "0fabf53d6f5e4d0ba6a71aaca4e4d64b"
CLIENT_SECRET = "99db601fe5f2497fbf80f0d67f0b5b03"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
# =======================================

# ---- Layout sizes ----
LANDSCAPE_W, LANDSCAPE_H = 600, 448
PORTRAIT_W, PORTRAIT_H   = 448, 600
TOP_ART_SIZE             = 448

# ---- Fonts ----
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title  = ImageFont.truetype(FONT_BOLD, 28)
font_artist = ImageFont.truetype(FONT_REG, 22)
font_header = ImageFont.truetype(FONT_BOLD, 18)
font_list   = ImageFont.truetype(FONT_REG, 16)

# ---- Behavior knobs ----
IDLE_SECS     = 600
POLL_ACTIVE   = 5
POLL_IDLE     = 60
DEBOUNCE_MS   = 3000
TOP_CACHE_TTL = 21600

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
PANEL_W, PANEL_H = display.resolution  # e.g., 600x448 on Inky Impression 5.7

# ---- Orientation handling ----
def maybe_flip(img):
    return img.rotate(180) if FLIP_180 else img

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

def draw_now_playing(track, artist, art_url):
    if ORIENTATION == "portrait":
        draw_now_playing_portrait(track, artist, art_url)
    else:
        draw_now_playing_landscape(track, artist, art_url)

def draw_now_playing_portrait(track, artist, art_url):
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))

    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    max_w = PORTRAIT_W - margin*2
    track_draw  = truncate(draw, track,  font_title,  max_w)
    artist_draw = truncate(draw, artist, font_artist, max_w)
    draw.text((margin, y0 + 10), track_draw,  font=font_title,  fill=(255,255,255))
    draw.text((margin, y0 + 48), artist_draw, font=font_artist, fill=(230,230,230))

    display.set_image(maybe_flip(img.rotate(90, expand=True)))  # rotate portrait to fit
    display.show()

def draw_now_playing_landscape(track, artist, art_url):
    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    # album art on the left
    art = Image.open(BytesIO(requests.get(art_url).content)).convert("RGB")
    art = art.resize((LANDSCAPE_H, LANDSCAPE_H))  # square 448×448
    img.paste(art, (0, 0))

    # text area on the right
    margin = 16
    x0 = LANDSCAPE_H  # start of right column
    text_w = LANDSCAPE_W - x0 - margin
    draw.rectangle([x0, 0, LANDSCAPE_W, LANDSCAPE_H], fill=(0,0,0))

    track_draw  = truncate(draw, track,  font_title,  text_w - 2*margin)
    artist_draw = truncate(draw, artist, font_artist, text_w - 2*margin)
    draw.text((x0 + margin, 160), track_draw,  font=font_title,  fill=(255,255,255))
    draw.text((x0 + margin, 205), artist_draw, font=font_artist, fill=(200,200,200))

    display.set_image(maybe_flip(img))
    display.show()

# ---- Top Tracks (idle mode) ----
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

def draw_idle_top_list(top_items):
    if ORIENTATION == "portrait":
        draw_idle_top_list_portrait(top_items)
    else:
        draw_idle_top_list_landscape(top_items)

def draw_idle_top_list_landscape(top_items):
    img = Image.new("RGB", (LANDSCAPE_W, LANDSCAPE_H), (255,255,255))
    draw = ImageDraw.Draw(img)

    if not top_items:
        msg = "No top tracks"
        w = int(draw.textlength(msg, font=font_header))
        draw.text(((LANDSCAPE_W - w)//2, LANDSCAPE_H//2 - 10), msg, font=font_header, fill=(0,0,0))
        display.set_image(maybe_flip(img))
        display.show()
        return

    hero = top_items[0]
    art = Image.open(BytesIO(requests.get(hero["img"]).content)).convert("RGB")
    art = art.resize((LANDSCAPE_H, LANDSCAPE_H))
    img.paste(art, (0, 0))

    x0 = LANDSCAPE_H
    draw.rectangle([x0, 0, LANDSCAPE_W, LANDSCAPE_H], fill=(0,0,0))
    margin = 16
    draw.text((x0 + margin, 16), "Top this week", font=font_header, fill=(255,255,255))

    y = 50
    for i, t in enumerate(top_items[:6]):
        line = f"{t['name']} — {t['artist']}"
        line = truncate(draw, line, font_list, LANDSCAPE_W - x0 - 2*margin)
        draw.text((x0 + margin, y), line, font=font_list, fill=(230,230,230))
        y += 26

    display.set_image(maybe_flip(img))
    display.show()

def draw_idle_top_list_portrait(top_items):
    # fallback to original vertical layout
    hero = top_items[0]
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255,255,255))
    draw = ImageDraw.Draw(img)
    art = Image.open(BytesIO(requests.get(hero["img"]).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    margin = 12
    draw.text((margin, y0 + 8), "Top this week", font=font_header, fill=(255,255,255))
    display.set_image(maybe_flip(img.rotate(90, expand=True)))
    display.show()

# ---------------- main loop ----------------
last_track_id   = None
last_active_ts  = time.monotonic()
idle_shown      = False
last_idle_sig   = None

candidate_id         = None
candidate_first_seen = 0.0

print(f"[Init] Panel {PANEL_W}x{PANEL_H} | orientation={ORIENTATION}")

while True:
    sleep_s = POLL_ACTIVE
    try:
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
            if listened_ms >= DEBOUNCE_MS:
                if tid != last_track_id or idle_shown:
                    print(f"Now playing: {track} – {artist}")
                    draw_now_playing(track, artist, arturl)
                    last_track_id = tid
                    idle_shown = False

            sleep_s = POLL_ACTIVE

        else:
            idle_for = time.monotonic() - last_active_ts
            if idle_for >= IDLE_SECS:
                top_items = get_top_tracks(limit=7, time_range="short_term")
                if not idle_shown:
                    print("Idle mode: displaying top tracks")
                    draw_idle_top_list(top_items)
                    idle_shown = True
                sleep_s = POLL_IDLE
            else:
                sleep_s = POLL_ACTIVE

    except Exception as e:
        print("[ERROR]", e)
        sleep_s = max(sleep_s, 60)

    time.sleep(sleep_s)
