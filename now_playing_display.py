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

# Portrait canvas (we rotate at the end)
PORTRAIT_W, PORTRAIT_H = 448, 600
GRID_SIZE = 224  # 2x2 tiles fill top 448x448
ROTATE_DEG = 90  # flip to the 600x448 panel; use -90 if orientation is wrong

# Need top tracks permission
scope = "user-top-read"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

display = auto()
PANEL_W, PANEL_H = display.resolution  # 600 x 448 (Inky Impression 5.7")

# Fonts (adjust sizes if you want tighter text)
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title  = ImageFont.truetype(FONT_BOLD, 16)
font_artist = ImageFont.truetype(FONT_REG, 14)

def truncate(draw, text, font, max_w):
    """Truncate text with ellipsis to fit max_w."""
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

def fetch_top4():
    # short_term (last 4 weeks) or medium_term (6 months)
    items = sp.current_user_top_tracks(limit=4, time_range="short_term")["items"]
    top = []
    for it in items:
        name   = it["name"]
        artist = it["artists"][0]["name"]
        img    = it["album"]["images"][0]["url"]
        top.append((name, artist, img))
    return top

def draw_top4_grid():
    # Base portrait canvas
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Title band (optional)
    header_h = 40
    draw.rectangle([0, PORTRAIT_H - header_h, PORTRAIT_W, PORTRAIT_H], fill=(0,0,0))
    draw.text((12, PORTRAIT_H - header_h + 10), "Your Top Tracks", font=font_title, fill=(255,255,255))

    # Place 2x2 tiles in the top 448x448
    positions = [(0,0), (GRID_SIZE,0), (0,GRID_SIZE), (GRID_SIZE,GRID_SIZE)]
    max_text_w = GRID_SIZE - 10*2  # padding inside each tile

    top4 = fetch_top4()
    for (name, artist, url), (x, y) in zip(top4, positions):
        # Fetch art
        art = Image.open(BytesIO(requests.get(url).content)).convert("RGB")
        art = art.resize((GRID_SIZE, GRID_SIZE))
        img.paste(art, (x, y))

        # Overlay text band inside tile (bottom)
        band_h = 38
        draw.rectangle([x, y + GRID_SIZE - band_h, x + GRID_SIZE, y + GRID_SIZE], fill=(0,0,0))
        title_line  = truncate(draw, name,   font_title,  max_text_w)
        artist_line = truncate(draw, artist, font_artist, max_text_w)
        draw.text((x + 10, y + GRID_SIZE - band_h + 4),  title_line,  font=font_title,  fill=(255,255,255))
        draw.text((x + 10, y + GRID_SIZE - band_h + 20), artist_line, font=font_artist, fill=(220,220,220))

    # Rotate portrait to panel orientation and show
    rotated = img.rotate(ROTATE_DEG, expand=True)  # becomes 600x448
    display.set_image(rotated)
    display.show()

if __name__ == "__main__":
    try:
        draw_top4_grid()
    except Exception as e:
        print("[ERROR]", e)