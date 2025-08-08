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

# Portrait canvas; we rotate to the panel at the end
PORTRAIT_W, PORTRAIT_H = 448, 600
TOP_ART_SIZE = 448            # square art at top
TEXT_H = PORTRAIT_H - TOP_ART_SIZE  # 152 px
ROTATE_DEG = 90               # use -90 if orientation is flipped

# Need top-tracks access
scope = "user-top-read"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

display = auto()
PANEL_W, PANEL_H = display.resolution

# Fonts
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_header = ImageFont.truetype(FONT_BOLD, 18)
font_list   = ImageFont.truetype(FONT_REG, 16)

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

def fetch_top_tracks(limit=7):
    # short_term ≈ last ~4 weeks
    res = sp.current_user_top_tracks(limit=limit, time_range="short_term")
    items = res.get("items", [])
    # Return list of dicts with name, artist, image
    out = []
    for it in items:
        name   = it["name"]
        artist = it["artists"][0]["name"]
        img    = it["album"]["images"][0]["url"]
        out.append({"name": name, "artist": artist, "img": img})
    return out

def draw_top1_plus_list():
    top = fetch_top_tracks(limit=7)   # get a few extra so list can show up to 6
    if not top:
        # Nothing to show; make a simple placeholder
        img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        msg = "No top tracks available"
        w = int(draw.textlength(msg, font=font_header))
        draw.text(((PORTRAIT_W - w)//2, PORTRAIT_H//2 - 10), msg, font=font_header, fill=(0,0,0))
        rotated = img.rotate(ROTATE_DEG, expand=True)
        display.set_image(rotated)
        display.show()
        return

    # Base portrait
    img = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # --- Top track art (full 448x448) ---
    hero = top[0]
    art = Image.open(BytesIO(requests.get(hero["img"]).content)).convert("RGB")
    art = art.resize((TOP_ART_SIZE, TOP_ART_SIZE))
    img.paste(art, (0, 0))

    # --- Bottom text area ---
    margin_x = 12
    y0 = TOP_ART_SIZE
    draw.rectangle([0, y0, PORTRAIT_W, PORTRAIT_H], fill=(0, 0, 0))

    # Header
    header_text = "Top this week"
    draw.text((margin_x, y0 + 8), header_text, font=font_header, fill=(255, 255, 255))

    # Bullet list of the next top tracks (skip the top 1)
    list_y = y0 + 8 + 24  # below header
    line_h = 22           # tweak if you change font size
    max_lines = (TOP_ART_SIZE + TEXT_H - list_y) // line_h   # lines that fit
    max_w = PORTRAIT_W - margin_x*2

    others = top[0:]  # everything including the hero
    # We try to show up to 6 “others” if space allows
    for i, t in enumerate(others[:6]):
        if i >= max_lines:
            break
        line = f"{t['name']} — {t['artist']}"
        line = truncate(draw, line, font_list, max_w - 18)  # leave room for bullet
        # Draw bullet + text
        draw.text((margin_x, list_y + i*line_h), "•", font=font_list, fill=(220,220,220))
        draw.text((margin_x + 14, list_y + i*line_h), line, font=font_list, fill=(230,230,230))

    # Rotate portrait → panel and display
    rotated = img.rotate(ROTATE_DEG, expand=True)  # 600x448
    display.set_image(rotated)
    display.show()

if __name__ == "__main__":
    draw_top1_plus_list()