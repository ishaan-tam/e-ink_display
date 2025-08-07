import time
import requests
from io import BytesIO
from PIL import Image, ImageTk
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import tkinter as tk

# === FILL THESE IN ===
CLIENT_ID = "0fabf53d6f5e4d0ba6a71aaca4e4d64b"
CLIENT_SECRET = "99db601fe5f2497fbf80f0d67f0b5b03"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
# ======================

scope = "user-read-currently-playing"

# Auth with Spotify
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    open_browser=True
))

# GUI setup
window = tk.Tk()
window.title("Now Playing on Spotify")
window.geometry("500x500")
window.resizable(False, False)

canvas = tk.Canvas(window, width=500, height=500)
canvas.pack(fill="both", expand=True)

track_var = tk.StringVar()
artist_var = tk.StringVar()

track_label = tk.Label(window, textvariable=track_var, font=("Helvetica", 16), bg="black", fg="white")
artist_label = tk.Label(window, textvariable=artist_var, font=("Helvetica", 12), bg="black", fg="white")

canvas.create_window(250, 400, window=track_label)
canvas.create_window(250, 430, window=artist_label)

bg_img_ref = None  # Keep reference so image doesn't get garbage collected

def update_song():
    global bg_img_ref

    try:
        current = sp.current_user_playing_track()
        if current and current["is_playing"]:
            track = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            img_url = current["item"]["album"]["images"][0]["url"]

            track_var.set(f"{track}")
            artist_var.set(f"{artist}")

            # Download album art
            response = requests.get(img_url)
            img_data = BytesIO(response.content)
            pil_img = Image.open(img_data).resize((500, 500)).convert("RGB")
            bg_img_ref = ImageTk.PhotoImage(pil_img)

            # Set background image
            canvas.create_image(0, 0, image=bg_img_ref, anchor="nw")
            canvas.create_window(250, 400, window=track_label)
            canvas.create_window(250, 430, window=artist_label)

        else:
            track_var.set("No song playing.")
            artist_var.set("")

    except Exception as e:
        track_var.set("Error")
        artist_var.set(str(e))

    window.after(5000, update_song)

update_song()
window.mainloop()
