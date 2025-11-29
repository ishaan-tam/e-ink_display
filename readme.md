# Spotify E-Ink Smart Display

A Raspberry Pi–powered e-ink frame that displays Spotify Now Playing information, top weekly tracks, time/date, and additional widgets. The project includes both the software stack and the physical design (3D-printed mat + standard picture frame integration).

This repository documents the full system: the Python runtime, systemd service, Spotify API integration, UI design, presence-aware refresh logic, and the physical design process.

---

## Table of Contents
1. Overview  
2. Features  
3. Hardware  
4. Repository Structure  
5. Setup Guide  
6. System Architecture  
7. Design Decisions  
8. 3D-Printed Frame Mat  
9. Example Images  
10. Future Improvements  

---

## 1. Overview

This project converts a Raspberry Pi and an Inky e-ink panel into a minimal, low-power smart display.  
It is designed to be visually clean, refresh-efficient, and easy to deploy across multiple Pi units without manual reconfiguration.

The repository also contains the CAD files for the 3D-printed mat that allows the e-ink panel to fit flush inside a commercial metal picture frame.

---

## 2. Features

### Spotify Integration
- Now Playing screen with album art, multi-line song title, and artist name.
- Idle screen showing top tracks of the week with wrapped lines and clean typography.
- Album-art-driven color accents (optional).
- E-ink-friendly refresh strategy to reduce ghosting.

### UI Enhancements
- Taskbar with time (rounded to nearest 10 minutes) and date (e.g., `Mon, Nov 24`).
- Auto-adjusting layout based on a single `ALBUM_ART_SIDE` control variable.
- Landscape-first layout for wide frames.

### System Behavior
- Presence awareness: screen updates can pause when you are away from home.
- Graceful Spotify rate-limit handling.
- Modular systemd service that works on any Raspberry Pi user account.
- QR-based Spotify login via PKCE (planned).

### Extensibility
- Weather widget support (planned)
- Stock/finance dashboard (planned)
- NFC integration (planned)
- Photo-frame mode (future consideration)

---

## 3. Hardware

Below are placeholders for the required hardware components.  
Replace these with actual product links after uploading the README.

- Inky Impression 5.7" E-Ink Display  
  `[Display_Link_Here]`

- Raspberry Pi (Zero 2 W / 3 / 4)  
  `[Pi_Link_Here]`

- Metal Picture Frame  
  `[Frame_Link_Here]`

- USB-C / micro-USB power cable (angled recommended)  
  `[Power_Cable_Link_Here]`

- 3D Printed Mat (files in `/frame_mat/`)  
  `[No link needed — included here]`

---

## 4. Repository Structure

