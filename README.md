# OmniRemux — Web-Based Zero-Loss Video Remuxer & Transcoder

> A high-performance, drag-and-drop web application that remuxes and converts `.mkv` videos to Telegram-compatible `.mp4` format (and more) in **1 to 3 seconds** with **0% video loss**.

---

## ✨ Features

- **⚡ Zero-Loss Container Remuxing**: Copies video streams directly (`-c:v copy`) without re-encoding, preserving 100% original video bitrate and quality.
- **🔊 Telegram Web Audio Fix**: Automatically maps native `AAC` audio streams or converts incompatible `E-AC3` (Dolby Digital Plus) / `DTS` audio to AAC 256kbps stereo so audio plays with full volume on Telegram Web, Mobile, and web browsers.
- **🚀 Web FastStart**: Automatically places the MP4 `moov` atom at the beginning of the file for instant seeking and immediate streaming playback.
- **🎨 Obsidian Cyber-Workstation Interface**: Designed with a sleek dark aesthetic, neon glowing borders, and glassmorphic panels.
- **🔍 Deep Stream Inspector**: Probes video, audio, and subtitle streams, and extracts video thumbnails using FFmpeg.
- **📊 Real-Time Engine Telemetry**: High-tech progress bar, real-time throughput FPS, speed multiplier (e.g. `85x` to `400x`), ETA countdown, and collapsible live stdout/stderr terminal drawer.
- **🎬 In-Browser Video Player**: Preview converted videos in a built-in HTML5 modal player before saving.
- **📁 Windows Explorer Integration**: 1-click "Show in Folder" button to highlight the converted file in Windows Explorer.

---

## 🎯 Target Format Profiles

1. **Telegram & Web MP4 (Zero Loss Remux)** *(Default)*: Direct stream copy + AAC auto-select + Web FastStart.
2. **Universal MP4 (H.264 / AAC)**: Maximum compatibility across legacy devices, TVs, and mobile screens.
3. **WebM Stream (VP9 / Opus)**: Web and Discord-optimized container.
4. **Extract Audio (MP3 320kbps / AAC / WAV)**: 1-click pure soundtrack extraction.
5. **Smooth 24 FPS Animated GIF**: PaletteGen high-quality animated clips.

---

## 🛠️ Quick Start

### Requirements
- **Python 3.8+**
- **FFmpeg & FFprobe** installed and accessible in system `PATH`.

### Running Locally

1. Clone the repository:
   ```bash
   git clone https://github.com/ShaileshLambode/OmniRemu-Web-Based-Video-Remuxer-Transcoder.git
   cd OmniRemu-Web-Based-Video-Remuxer-Transcoder
   ```

2. Start the server:
   - On Windows, double-click `start.bat` or run:
     ```bash
     python server.py 5050
     ```

3. Open **http://localhost:5050** in your browser.

4. When finished, click **"Stop"** in the web header or double-click `stop.bat`.

---

## 📂 Project Structure

```
omni-remux/
├── server.py           # Multi-threaded Python server & FFmpeg engine
├── start.bat           # 1-click Windows launcher
├── stop.bat            # Windows stop script with PID tracking
├── LICENSE             # MIT License
├── static/
│   └── index.html      # Cyber-workstation single-page application
├── tests/              # Automated test suite (unit, security, audio matrix, probe)
│   └── fixtures/       # Synthetic test media fixtures generator
├── uploads/            # Temporary upload directory (gitignored)
├── outputs/            # Converted video files (gitignored)
├── thumbs/             # Extracted video thumbnail cache (gitignored)
└── README.md
```

---

## 🧪 Automated Testing

OmniRemux includes an automated test suite covering origin validation, CSRF tokens, audio matrix configurations, stream probing, and FFmpeg conversion pipelines.

1. Generate synthetic test media fixtures:
   ```bash
   python ./tests/fixtures/make_test_media.py
   ```

2. Run the full test suite:
   ```bash
   python -m unittest discover -s tests -v
   ```

---

## 📄 License

MIT License. Open-source and free to use.
