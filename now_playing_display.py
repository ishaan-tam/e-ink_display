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

ROTATE_DEG = 90          # set to -90 if orientation is flipped
PORTRAIT_W = 448
PORTRAIT_H = 600
ART_SIZE   = 448         # square album art at top
TEXT_H     = PORTRAIT_H - ART_SIZE  # 152 px for text area

scope = "user-read-currently-playing"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

display = auto()
PANEL_W, PANEL_H = display.resolution  # should be 600x448 on the 5.7"

# Fonts (adjust sizes if needed)
font_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
font_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",       22)

last_track_id = None

def _truncate_to_width(text, font, max_w, draw):
    """Truncate with ellipsis so it fits max_w."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    # binary-ish trim
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        trial = text[:mid] + ell
        if draw.textlength(trial, font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return text[:max(0, lo-1)] + ell

def draw_display(track, artist, album_art_url):
    # Base portrait canvas (we'll rotate it to the panel at the end)
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # --- album art (top 448x448) ---
    art = Image.open(BytesIO(requests.get(album_art_url).content)).convert("RGB")
    art = art.resize((ART_SIZE, ART_SIZE))
    img.paste(art, (0, 0))

    # --- text area (bottom 152 px) ---
    margin = 12
    text_y = ART_SIZE + 10
    text_w = PORTRAIT_W - 2*margin
    # background bar for contrast (optional: use semi-transparent look if you want)
    draw.rectangle([0, ART_SIZE, PORTRAIT_W, PORTRAIT_H], fill=(0, 0, 0))

    # fit text to width
    track_draw = _truncate_to_width(track,  font_title,  text_w, draw)
    artist_draw = _truncate_to_width(artist, font_artist, text_w, draw)

    draw.text((margin, text_y), track_draw,  font=font_title,  fill=(255, 255, 255))
    draw.text((margin, text_y + 36), artist_draw, font=font_artist, fill=(255, 255, 255))

    # rotate portrait -> panel’s 600x448 landscape buffer
    rotated = img.rotate(ROTATE_DEG, expand=True)  # becomes 600x448
    display.set_image(rotated)
    display.show()

while True:
    try:
        current = sp.current_user_playing_track()
        if current and current["is_playing"]:
            track_id = current["item"]["id"]
            if track_id != last_track_id:
                track = current["item"]["name"]
                artist = current["item"]["artists"][0]["name"]
                album_art_url = current["item"]["album"]["images"][0]["url"]
                print(f"Now playing: {track} – {artist}")
                draw_display(track, artist, album_art_url)
                last_track_id = track_id
        else:
            print("No song currently playing.")
    except Exception as e:
        print(f"[ERROR] Spotify polling failed: {e}")

    time.sleep(30)  # e-ink friendly; lower only if you really need faster changes
