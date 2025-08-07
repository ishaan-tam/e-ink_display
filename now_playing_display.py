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

scope = "user-read-currently-playing"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=False
))

# Setup Inky display
display = auto()
WIDTH, HEIGHT = display.resolution

# Use system fonts (adjust path if needed)
font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
font_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)

last_track_id = None

def draw_display(track, artist, album_art_url):
    try:
        # Download album art
        response = requests.get(album_art_url)
        art = Image.open(BytesIO(response.content)).resize((WIDTH, HEIGHT)).convert("RGB")

        # Draw text overlay
        draw = ImageDraw.Draw(art)
        draw.rectangle([0, HEIGHT - 60, WIDTH, HEIGHT], fill=(0, 0, 0))
        draw.text((10, HEIGHT - 55), track, font=font_title, fill=(255, 255, 255))
        draw.text((10, HEIGHT - 30), artist, font=font_artist, fill=(255, 255, 255))

        # Update the e-ink display
        display.set_image(art)
        display.show()

    except Exception as e:
        print(f"[ERROR] Failed to draw display: {e}")

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

    time.sleep(30)  # Poll every 30s to preserve e-ink
