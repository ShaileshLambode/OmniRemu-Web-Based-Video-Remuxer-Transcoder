import os
import sys
import json
import time
import uuid
import shutil
import urllib.parse
import subprocess
import threading
import secrets
import atexit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Base Directories
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
UPLOADS_DIR = os.path.join(APP_DIR, "uploads")
OUTPUTS_DIR = os.path.join(APP_DIR, "outputs")
THUMBS_DIR = os.path.join(APP_DIR, "thumbs")
WORKSPACE_DIR = APP_DIR

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".webm", ".ts", ".m2ts", ".flv", ".wmv", ".m4v"}
IGNORED_SCAN_DIRS = {
    ".git", ".vscode", ".idea", "venv", ".venv", "env",
    "__pycache__", "node_modules", "thumbs", ".gemini", ".agents",
    "tests", "docs"
}

for d in [STATIC_DIR, UPLOADS_DIR, OUTPUTS_DIR, THUMBS_DIR]:
    os.makedirs(d, exist_ok=True)

# Security and Concurrency Configuration
SERVER_PORT = 5050
SESSION_TOKEN = secrets.token_hex(16)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB limit
MAX_CONCURRENT_JOBS = 2
JOB_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_JOBS)
MAX_JOB_HISTORY = 50

PID_FILE = os.path.join(APP_DIR, ".omni.pid")

def write_pid_file():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

def remove_pid_file():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

atexit.register(remove_pid_file)

# In-memory Job Tracker
JOBS = {}
JOBS_LOCK = threading.Lock()

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def format_seconds(seconds):
    if not seconds or seconds < 0:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def parse_time_str(time_str):
    if not time_str:
        return 0.0
    parts = time_str.strip().split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except Exception:
        return 0.0
    return 0.0

def parse_fps(fps_str):
    if not fps_str:
        return 24.0
    if isinstance(fps_str, (int, float)):
        return float(fps_str) if fps_str > 0 else 24.0
    fps_str = str(fps_str).strip()
    try:
        if "/" in fps_str:
            num_s, den_s = fps_str.split("/", 1)
            num = float(num_s)
            den = float(den_s)
            if den == 0.0 or num == 0.0:
                return 24.0
            val = round(num / den, 2)
            return val if val > 0 else 24.0
        val = float(fps_str)
        return round(val, 2) if val > 0 else 24.0
    except Exception:
        return 24.0

def sanitize_filename(filename, default_ext=".mkv"):
    if not filename or not str(filename).strip():
        return f"upload_{int(time.time())}{default_ext}"
    filename = str(filename).strip().replace("\\", "/")
    filename = os.path.basename(filename)
    illegal_chars = set('<>:"/\\|?*')
    cleaned = "".join(c for c in filename if c not in illegal_chars and ord(c) >= 32)
    cleaned = cleaned.strip(". ")
    if not cleaned:
        cleaned = f"upload_{int(time.time())}{default_ext}"
    return cleaned

def resolve_safe_path(target_path, base_dir=None):
    """
    Confines target_path within base_dir (defaults to APP_DIR).
    Returns resolved absolute path if safe and exists, or None if invalid/escaping.
    Rejects UNC paths, directory traversal, drive letter escapes, and missing files.
    """
    if not target_path or not str(target_path).strip():
        return None
    raw = str(target_path).strip()

    # Reject Windows UNC network paths
    if raw.startswith("\\\\") or raw.startswith("//"):
        return None

    # Normalize backslashes on POSIX systems so Windows-style traversals are properly confined
    if os.sep == "/":
        raw = raw.replace("\\", "/")

    allowed_root = os.path.realpath(base_dir or APP_DIR)

    # If target_path is not absolute, check inside UPLOADS_DIR, OUTPUTS_DIR, or APP_DIR
    if not os.path.isabs(raw):
        for d in [UPLOADS_DIR, OUTPUTS_DIR, allowed_root]:
            candidate = os.path.realpath(os.path.join(d, raw))
            try:
                if os.path.commonpath([allowed_root, candidate]) == allowed_root and os.path.exists(candidate):
                    return candidate
            except ValueError:
                pass
        return None

    resolved = os.path.realpath(raw)
    try:
        if os.path.commonpath([allowed_root, resolved]) != allowed_root:
            return None
    except ValueError:
        return None

    return resolved if os.path.exists(resolved) else None

def get_unique_output_path(base_name, ext, outputs_dir):
    base_name = os.path.basename(str(base_name).strip())
    illegal_chars = set('<>:"/\\|?*')
    base_name = "".join(c for c in base_name if c not in illegal_chars and ord(c) >= 32).strip(". ")
    if not base_name:
        base_name = f"output_{int(time.time())}"

    candidate_name = f"{base_name}_converted{ext}"
    candidate_path = os.path.join(outputs_dir, candidate_name)
    if not os.path.exists(candidate_path):
        return candidate_name, candidate_path

    counter = 1
    while os.path.exists(candidate_path):
        candidate_name = f"{base_name}_converted ({counter}){ext}"
        candidate_path = os.path.join(outputs_dir, candidate_name)
        counter += 1

    return candidate_name, candidate_path

def probe_file(file_path):
    if not os.path.exists(file_path):
        return None
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout)
        
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        
        duration = float(fmt.get("duration", 0.0))
        size_bytes = int(fmt.get("size", os.path.getsize(file_path)))
        
        video_streams = []
        audio_streams = []
        subtitle_streams = []
        attached_pics = []
        
        for s in streams:
            ctype = s.get("codec_type")
            idx = s.get("index")
            codec = s.get("codec_name", "unknown")
            disp = s.get("disposition", {})
            tags = s.get("tags", {})
            
            if disp.get("attached_pic") == 1 or codec == "mjpeg" and ctype == "video" and disp.get("default") == 0:
                attached_pics.append({
                    "index": idx,
                    "codec": codec,
                    "filename": tags.get("filename", "cover.jpg")
                })
            elif ctype == "video":
                video_streams.append({
                    "index": idx,
                    "codec": codec,
                    "codec_long": s.get("codec_long_name", codec),
                    "profile": s.get("profile", ""),
                    "width": s.get("width"),
                    "height": s.get("height"),
                    "fps": parse_fps(s.get("r_frame_rate", "24/1")),
                    "bitrate": int(s.get("bit_rate", 0)) if s.get("bit_rate") else None,
                    "pixel_format": s.get("pix_fmt", "")
                })
            elif ctype == "audio":
                audio_streams.append({
                    "index": idx,
                    "codec": codec,
                    "channels": s.get("channels", 2),
                    "channel_layout": s.get("channel_layout", "stereo"),
                    "sample_rate": s.get("sample_rate", "48000"),
                    "bitrate": int(s.get("bit_rate", 0)) if s.get("bit_rate") else None,
                    "language": tags.get("language", "und"),
                    "title": tags.get("title", ""),
                    "is_aac": (codec.lower() == "aac"),
                    "is_eac3": ("eac3" in codec.lower() or "ddp" in codec.lower() or "dts" in codec.lower())
                })
            elif ctype == "subtitle":
                subtitle_streams.append({
                    "index": idx,
                    "codec": codec,
                    "language": tags.get("language", "und"),
                    "title": tags.get("title", "")
                })
                
        # Generate thumbnail
        thumb_name = f"thumb_{abs(hash(file_path))}.jpg"
        thumb_path = os.path.join(THUMBS_DIR, thumb_name)
        if not os.path.exists(thumb_path):
            ss_time = min(15.0, duration * 0.1) if duration > 5 else 1.0
            t_cmd = [
                "ffmpeg", "-y", "-ss", str(ss_time), "-i", file_path,
                "-vframes", "1", "-vf", "scale=640:-1", "-q:v", "3", thumb_path
            ]
            subprocess.run(t_cmd, capture_output=True)
            
        has_thumb = os.path.exists(thumb_path)
        
        return {
            "path": file_path,
            "filename": os.path.basename(file_path),
            "size": size_bytes,
            "size_formatted": format_bytes(size_bytes),
            "duration": duration,
            "duration_formatted": format_seconds(duration),
            "container": fmt.get("format_name", "unknown"),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
            "subtitle_streams": subtitle_streams,
            "attached_pics": attached_pics,
            "thumbnail_url": f"/api/thumbnail/{thumb_name}" if has_thumb else None
        }
    except Exception as e:
        print("Probe error:", e)
        return None

def build_audio_flags(probe_info, audio_strategy, preset):
    """
    Constructs ffmpeg audio mapping and codec arguments based on audio_strategy and preset.
    Supported strategies:
      - 'mute': removes audio completely (-an)
      - 'copy': stream copy without re-encoding
      - 'aac_stereo': force AAC 256k 2-channel stereo
      - 'aac_51': force AAC 384k 6-channel 5.1 surround
      - 'auto': AAC direct copy if available, else transcode to AAC 256k stereo (or opus for webm)
    """
    audio_streams = probe_info.get("audio_streams", []) if probe_info else []
    if not audio_streams or audio_strategy == "mute":
        return ["-an"]

    first_a = audio_streams[0]
    first_a_idx = first_a["index"]
    aac_stream = next((a for a in audio_streams if a.get("is_aac")), None)
    aac_idx = aac_stream["index"] if aac_stream else None

    # Audio extraction presets handle their own codecs
    if preset in ["audio_mp3", "audio_aac", "audio_wav"]:
        return ["-map", f"0:{first_a_idx}"]

    flags = []

    if audio_strategy == "copy":
        for a in audio_streams:
            flags.extend(["-map", f"0:{a['index']}"])
        flags.extend(["-c:a", "copy"])
    elif audio_strategy == "aac_stereo":
        flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "aac", "-b:a", "256k", "-ac", "2"])
    elif audio_strategy == "aac_51":
        flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "aac", "-b:a", "384k", "-ac", "6"])
    else:  # "auto" or default
        if preset == "telegram_web_mp4":
            if aac_idx is not None:
                flags.extend(["-map", f"0:{aac_idx}", "-c:a", "copy"])
            else:
                flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "aac", "-b:a", "256k", "-ac", "2"])
        elif preset == "universal_mp4":
            flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        elif preset == "webm":
            flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "libopus", "-b:a", "128k"])
        elif preset == "gif":
            flags = ["-an"]
        else:
            flags.extend(["-map", f"0:{first_a_idx}", "-c:a", "copy"])

    return flags

def run_conversion_job(job_id, options):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return

    with JOB_SEMAPHORE:
        with JOBS_LOCK:
            if job.get("cancelled"):
                return
            job["status"] = "processing"
            job["start_time"] = time.time()
            
        input_path = options.get("input_path")
        preset = options.get("preset", "telegram_web_mp4")
        custom_name = options.get("custom_filename")
    
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        if custom_name and custom_name.strip():
            base_name = os.path.splitext(custom_name.strip())[0]
        
        probe_info = options.get("probe_info") or probe_file(input_path)
        total_duration = probe_info.get("duration", 0.0) if probe_info else 0.0
    
        # Determine output extension and ffmpeg flags
        ext = ".mp4"
        if preset == "webm":
            ext = ".webm"
        elif preset == "audio_mp3":
            ext = ".mp3"
        elif preset == "audio_aac":
            ext = ".m4a"
        elif preset == "audio_wav":
            ext = ".wav"
        elif preset == "gif":
            ext = ".gif"
        elif preset == "mkv":
            ext = ".mkv"
        
        output_filename, output_path = get_unique_output_path(base_name, ext, OUTPUTS_DIR)
    
        # Check if user specified audio strategy, resolution, etc.
        audio_strategy = options.get("audio_strategy", "auto")
        resolution = options.get("resolution", "original")
        crf = options.get("crf", 18)
        faststart = options.get("faststart", True)
        trim_start = options.get("trim_start")
        trim_end = options.get("trim_end")
    
        # Calculate effective target duration for accurate progress and ETA
        target_duration = total_duration
        t_start = parse_time_str(trim_start) if trim_start else 0.0
        t_end = parse_time_str(trim_end) if trim_end else 0.0
        if t_end > t_start:
            target_duration = t_end - t_start
        elif t_start > 0 and total_duration > t_start:
            target_duration = total_duration - t_start

        video_streams = probe_info.get("video_streams", []) if probe_info else []
        audio_streams = probe_info.get("audio_streams", []) if probe_info else []
        has_video = len(video_streams) > 0
        has_audio = len(audio_streams) > 0

        if not has_video and not has_audio:
            with JOBS_LOCK:
                job["status"] = "failed"
                job["error"] = "Input file contains no playable video or audio streams."
                job["logs"].append("[omni-engine] ERROR: No valid video or audio streams detected.")
            return

        if preset == "gif" and not has_video:
            with JOBS_LOCK:
                job["status"] = "failed"
                job["error"] = "Input file contains no video stream to generate a GIF."
                job["logs"].append("[omni-engine] ERROR: Video stream required for GIF generation.")
            return

        v_idx = video_streams[0]["index"] if has_video else None
                
        cmd = ["ffmpeg", "-y"]
    
        # Trim parameters before input for fast seek
        if trim_start and trim_start.strip():
            cmd.extend(["-ss", trim_start.strip()])
        if trim_end and trim_end.strip():
            cmd.extend(["-to", trim_end.strip()])
        
        cmd.extend(["-i", input_path])
    
        # Command Construction by Preset
        if preset == "telegram_web_mp4":
            if has_video:
                cmd.extend(["-map", f"0:{v_idx}", "-c:v", "copy"])
            cmd.extend(build_audio_flags(probe_info, audio_strategy, preset))
            if faststart and ext in [".mp4", ".m4a"]:
                cmd.extend(["-movflags", "+faststart"])
            
        elif preset == "universal_mp4":
            if has_video:
                cmd.extend(["-map", f"0:{v_idx}"])
                vf_filters = []
                if resolution == "1080p":
                    vf_filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
                elif resolution == "720p":
                    vf_filters.append("scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2")
                elif resolution == "480p":
                    vf_filters.append("scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2")
                
                if vf_filters:
                    cmd.extend(["-vf", ",".join(vf_filters)])
                
                cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)])
            
            cmd.extend(build_audio_flags(probe_info, audio_strategy, preset))
            if faststart and ext in [".mp4", ".m4a"]:
                cmd.extend(["-movflags", "+faststart"])
            
        elif preset == "webm":
            if has_video:
                cmd.extend(["-map", f"0:{v_idx}", "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0"])
            cmd.extend(build_audio_flags(probe_info, audio_strategy, preset))
            
        elif preset in ["audio_mp3", "audio_aac", "audio_wav"]:
            cmd.extend(["-vn"])
            if has_audio:
                first_a_idx = audio_streams[0]["index"]
                cmd.extend(["-map", f"0:{first_a_idx}"])
            if preset == "audio_mp3":
                cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
            elif preset == "audio_aac":
                cmd.extend(["-c:a", "aac", "-b:a", "256k"])
            elif preset == "audio_wav":
                cmd.extend(["-c:a", "pcm_s16le"])
            
        elif preset == "gif":
            if has_video:
                cmd.extend(["-map", f"0:{v_idx}"])
            cmd.extend(["-vf", "fps=24,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse", "-an"])
        
        cmd.extend(["-progress", "pipe:1", output_path])
    
        log_cmd_str = " ".join([f'"{x}"' if " " in x else x for x in cmd])
    
        with JOBS_LOCK:
            job["cmd"] = log_cmd_str
            job["output_filename"] = output_filename
            job["output_path"] = output_path
            job["logs"].append(f"[omni-engine] Executing: {log_cmd_str}")
        
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace"
            )
            with JOBS_LOCK:
                job["proc"] = proc
            
            def read_stderr(p):
                for line in p.stderr:
                    line = line.strip()
                    if line:
                        with JOBS_LOCK:
                            job["logs"].append(line)
                            if len(job["logs"]) > 300:
                                job["logs"].pop(0)
                            
            t_err = threading.Thread(target=read_stderr, args=(proc,))
            t_err.daemon = True
            t_err.start()
        
            # Read progress from stdout
            for line in proc.stdout:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                
                    with JOBS_LOCK:
                        if k == "out_time_us":
                            try:
                                cur_time = float(v) / 1000000.0
                                job["cur_time"] = cur_time
                                if target_duration > 0:
                                    job["progress"] = min(99.5, round((cur_time / target_duration) * 100, 1))
                                    elapsed = time.time() - job["start_time"]
                                    if cur_time > 0 and elapsed > 0:
                                        eta = (target_duration - cur_time) / (cur_time / elapsed)
                                        job["eta"] = max(0, int(eta))
                            except Exception:
                                pass
                        elif k == "fps":
                            job["fps"] = v
                        elif k == "speed":
                            job["speed"] = v
                        elif k == "total_size":
                            try:
                                job["processed_bytes"] = int(v)
                                job["processed_formatted"] = format_bytes(int(v))
                            except Exception:
                                pass
                            
            proc.wait()
            t_err.join(timeout=1.0)
        
            duration = round(time.time() - job["start_time"], 2)
            out_exists = os.path.exists(output_path)
            out_size = os.path.getsize(output_path) if out_exists else 0
        
            with JOBS_LOCK:
                if job.get("cancelled"):
                    job["status"] = "cancelled"
                    job["logs"].append("[omni-engine] Process was cancelled by user.")
                    if out_exists:
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass
                elif proc.returncode == 0 and out_exists:
                    job["status"] = "completed"
                    job["progress"] = 100.0
                    job["duration_seconds"] = duration
                    job["output_size"] = out_size
                    job["output_size_formatted"] = format_bytes(out_size)
                    job["logs"].append(f"[omni-engine] Conversion SUCCESS in {duration}s! Output size: {format_bytes(out_size)}")
                else:
                    job["status"] = "failed"
                    job["error"] = f"FFmpeg exited with code {proc.returncode}"
                    job["logs"].append(f"[omni-engine] ERROR: Process failed with code {proc.returncode}")
                    if out_exists:
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass
                
        except Exception as e:
            with JOBS_LOCK:
                if not job.get("cancelled"):
                    job["status"] = "failed"
                    job["error"] = str(e)
                    job["logs"].append(f"[omni-engine] EXCEPTION: {e}")

def reveal_in_file_manager(target_path=None):
    """
    Reveals the target file in Windows Explorer (or system file manager),
    highlighting the file if it exists, or opening the folder.
    Confined strictly within safe workspace boundaries.
    """
    if target_path and str(target_path).strip():
        safe_path = resolve_safe_path(target_path)
        if safe_path:
            target_path = safe_path
        else:
            alt_path = os.path.join(OUTPUTS_DIR, os.path.basename(str(target_path).strip()))
            target_path = alt_path if os.path.exists(alt_path) else OUTPUTS_DIR
    else:
        target_path = OUTPUTS_DIR

    target_path = os.path.normpath(os.path.abspath(target_path))

    if sys.platform == "win32":
        if os.path.isfile(target_path):
            # In Windows Explorer, /select, must remain UNQUOTED and immediately precede the quoted path:
            # e.g.: explorer.exe /select,"C:\path\to\file with spaces.mp4"
            # Passing a formatted string directly to subprocess.Popen prevents Python's
            # list2cmdline from wrapping '/select,...' in quotes when spaces are present.
            try:
                cmd = f'explorer.exe /select,"{target_path}"'
                subprocess.Popen(cmd)
                return True, target_path
            except Exception:
                pass

            # Fallback 1: Open parent folder via explorer
            try:
                folder = os.path.dirname(target_path)
                subprocess.Popen(f'explorer.exe "{folder}"')
                return True, folder
            except Exception:
                pass

            # Fallback 2: Open parent folder with os.startfile
            try:
                folder = os.path.dirname(target_path)
                os.startfile(folder)
                return True, folder
            except Exception as e:
                return False, str(e)
        else:
            try:
                subprocess.Popen(f'explorer.exe "{target_path}"')
                return True, target_path
            except Exception:
                pass

            try:
                os.startfile(target_path)
                return True, target_path
            except Exception as e:
                return False, str(e)

    elif sys.platform == "darwin":  # macOS
        try:
            if os.path.isfile(target_path):
                subprocess.Popen(["open", "-R", target_path])
            else:
                subprocess.Popen(["open", target_path])
            return True, target_path
        except Exception as e:
            return False, str(e)

    else:  # Linux / Unix
        try:
            folder = os.path.dirname(target_path) if os.path.isfile(target_path) else target_path
            subprocess.Popen(["xdg-open", folder])
            return True, folder
        except Exception as e:
            return False, str(e)

class OmniRequestHandler(BaseHTTPRequestHandler):
    @property
    def current_port(self):
        return getattr(self.server, "server_port", SERVER_PORT)

    def is_trusted_host(self):
        host = self.headers.get("Host")
        if not host:
            return True
        host = host.strip().lower()
        if host.startswith("["):
            bracket_end = host.find("]")
            host_name = host[1:bracket_end] if bracket_end != -1 else host
        else:
            host_name = host.split(":")[0].strip()
        return host_name in ["localhost", "127.0.0.1", "::1"]

    def is_trusted_origin(self):
        if not self.is_trusted_host():
            return False

        origin = self.headers.get("Origin")
        if not origin:
            # Same-origin direct navigation or local tools without Origin header
            return True

        try:
            parsed = urllib.parse.urlparse(origin)
            orig_host = (parsed.hostname or "").strip().lower()
            orig_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if orig_host in ["localhost", "127.0.0.1"] and orig_port == self.current_port:
                return True
        except Exception:
            return False

        return False

    def validate_session_token(self):
        token = self.headers.get("X-Omni-Token")
        if not token:
            return False
        return secrets.compare_digest(token, SESSION_TOKEN)

    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin and self.is_trusted_origin():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Omni-Token, X-File-Name, Range")
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        if not self.is_trusted_origin():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/" or path == "/index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Inject unpredictable CSRF session token
                content = content.replace(
                    '<meta name="omni-token" content=""/>',
                    f'<meta name="omni-token" content="{SESSION_TOKEN}"/>'
                )
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html not found")
            return

        elif path == "/api/status":
            # Hardware and version info
            ff_ver = "FFmpeg 8.1"
            try:
                res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
                ff_ver = res.stdout.splitlines()[0] if res.stdout else "FFmpeg 8.1"
            except Exception:
                pass
                
            self.send_json({
                "status": "ready",
                "ffmpeg_version": ff_ver,
                "workspace": WORKSPACE_DIR,
                "active_jobs": len([j for j in JOBS.values() if j.get("status") == "processing"])
            })
            return

        elif path == "/api/local-files":
            if not self.is_trusted_origin():
                self.send_json({"error": "Forbidden: Untrusted Origin"}, status=403)
                return

            files_found = []
            for root, dirs, files in os.walk(APP_DIR):
                dirs[:] = [d for d in dirs if d not in IGNORED_SCAN_DIRS and not d.startswith(".")]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in VIDEO_EXTENSIONS:
                        full = os.path.join(root, f)
                        try:
                            stat = os.stat(full)
                            files_found.append({
                                "filename": f,
                                "path": full,
                                "rel_path": os.path.relpath(full, APP_DIR),
                                "size": stat.st_size,
                                "size_formatted": format_bytes(stat.st_size),
                                "mtime": stat.st_mtime
                            })
                        except Exception:
                            pass
            files_found.sort(key=lambda x: x["mtime"], reverse=True)
            self.send_json({"files": files_found})
            return

        elif path.startswith("/api/jobs/"):
            if not self.is_trusted_origin():
                self.send_json({"error": "Forbidden: Untrusted Origin"}, status=403)
                return

            job_id = path.replace("/api/jobs/", "").strip("/")
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    self.send_json({"error": "Job not found"}, status=404)
                    return
                # Return snapshot without proc object
                safe_job = {k: v for k, v in job.items() if k != "proc"}
            self.send_json(safe_job)
            return

        elif path.startswith("/api/thumbnail/"):
            thumb_name = os.path.basename(path.replace("/api/thumbnail/", ""))
            thumb_path = os.path.join(THUMBS_DIR, thumb_name)
            safe_thumb = resolve_safe_path(thumb_path, THUMBS_DIR)
            if safe_thumb and os.path.exists(safe_thumb):
                self.serve_file(safe_thumb, "image/jpeg")
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/api/preview/"):
            fname = os.path.basename(path.replace("/api/preview/", ""))
            safe_path = resolve_safe_path(fname)
            if safe_path and os.path.exists(safe_path):
                self.serve_video_range(safe_path)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/api/download/"):
            fname = os.path.basename(path.replace("/api/download/", ""))
            safe_path = resolve_safe_path(fname)
            if safe_path and os.path.exists(safe_path):
                self.serve_download(safe_path, fname)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/static/"):
            rel_file = path.replace("/static/", "")
            full = resolve_safe_path(rel_file, STATIC_DIR)
            if full and os.path.exists(full) and os.path.isfile(full):
                mime = "text/plain"
                if full.endswith(".html"): mime = "text/html; charset=utf-8"
                elif full.endswith(".css"): mime = "text/css; charset=utf-8"
                elif full.endswith(".js"): mime = "application/javascript; charset=utf-8"
                elif full.endswith(".svg"): mime = "image/svg+xml"
                elif full.endswith(".png"): mime = "image/png"
                self.serve_file(full, mime)
            else:
                self.send_response(404)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if not self.is_trusted_origin():
            self.send_json({"error": "Forbidden: Untrusted Origin or Host"}, status=403)
            return

        if not self.validate_session_token():
            self.send_json({"error": "Forbidden: Invalid or missing X-Omni-Token"}, status=403)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            content_length_header = self.headers.get("Content-Length")
            try:
                content_length = int(content_length_header) if content_length_header else 0
            except ValueError:
                self.send_json({"error": "Bad Request: Invalid Content-Length"}, status=400)
                return

            if content_length <= 0:
                self.send_json({"error": "Bad Request: Content-Length required"}, status=400)
                return

            if content_length > MAX_UPLOAD_SIZE:
                self.send_json({"error": f"Payload Too Large: Exceeds {format_bytes(MAX_UPLOAD_SIZE)} limit"}, status=413)
                return

            filename = self.headers.get("X-File-Name")
            if filename:
                filename = urllib.parse.unquote(filename)
            else:
                filename = f"upload_{uuid.uuid4().hex[:8]}.mkv"

            safe_filename = sanitize_filename(filename)
            dest_path = os.path.join(UPLOADS_DIR, safe_filename)

            remaining = content_length
            try:
                with open(dest_path, "wb") as f:
                    while remaining > 0:
                        chunk_size = min(remaining, 65536)
                        chunk = self.rfile.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)

                if remaining > 0:
                    if os.path.exists(dest_path):
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    self.send_json({"error": "Upload incomplete / client disconnected"}, status=400)
                    return
            except Exception as e:
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                self.send_json({"error": f"Upload failed: {e}"}, status=500)
                return

            probe = probe_file(dest_path)
            self.send_json({
                "status": "uploaded",
                "path": dest_path,
                "filename": safe_filename,
                "probe": probe
            })
            return

        # JSON endpoints
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        data = {}
        if post_data:
            try:
                data = json.loads(post_data.decode("utf-8"))
            except Exception:
                pass

        if path == "/api/probe":
            raw_path = data.get("path")
            if not raw_path and data.get("filename"):
                raw_path = os.path.join(UPLOADS_DIR, data.get("filename"))
            safe_target = resolve_safe_path(raw_path)
            if not safe_target:
                self.send_json({"error": "File does not exist or access denied"}, status=400)
                return
            probe_result = probe_file(safe_target)
            if probe_result:
                self.send_json(probe_result)
            else:
                self.send_json({"error": "Failed to probe file"}, status=500)
            return

        elif path == "/api/convert":
            raw_path = data.get("path")
            if not raw_path and data.get("filename"):
                raw_path = os.path.join(UPLOADS_DIR, data.get("filename"))
            safe_input = resolve_safe_path(raw_path)
            if not safe_input:
                self.send_json({"error": "Input file not found or access denied"}, status=400)
                return

            preset = data.get("preset", "telegram_web_mp4")
            if preset not in ["telegram_web_mp4", "universal_mp4", "webm", "audio_mp3", "audio_aac", "audio_wav", "gif", "mkv"]:
                self.send_json({"error": "Invalid preset specified"}, status=400)
                return

            resolution = data.get("resolution", "original")
            if resolution not in ["original", "1080p", "720p", "480p"]:
                resolution = "original"
            data["resolution"] = resolution

            try:
                crf = int(data.get("crf", 18))
                crf = max(0, min(51, crf))
            except (ValueError, TypeError):
                crf = 18
            data["crf"] = crf

            trim_start = str(data.get("trim_start", "")).strip()
            trim_end = str(data.get("trim_end", "")).strip()
            t_start = parse_time_str(trim_start) if trim_start else 0.0
            t_end = parse_time_str(trim_end) if trim_end else 0.0
            if t_start < 0 or t_end < 0:
                self.send_json({"error": "Trim timestamps cannot be negative"}, status=400)
                return
            if t_end > 0 and t_end <= t_start:
                self.send_json({"error": "Trim end must be greater than trim start"}, status=400)
                return

            custom_name = data.get("custom_filename")
            if custom_name:
                data["custom_filename"] = os.path.basename(str(custom_name).strip())

            job_id = uuid.uuid4().hex[:12]
            with JOBS_LOCK:
                if len(JOBS) >= MAX_JOB_HISTORY:
                    finished = [jid for jid, j in JOBS.items() if j.get("status") in ["completed", "failed", "cancelled"]]
                    for old_id in finished[:len(JOBS) - MAX_JOB_HISTORY + 1]:
                        del JOBS[old_id]

                JOBS[job_id] = {
                    "id": job_id,
                    "input_path": safe_input,
                    "filename": os.path.basename(safe_input),
                    "preset": preset,
                    "status": "queued",
                    "progress": 0.0,
                    "fps": 0,
                    "speed": "0x",
                    "eta": 0,
                    "processed_bytes": 0,
                    "processed_formatted": "0 B",
                    "output_filename": None,
                    "output_path": None,
                    "logs": [f"[omni-engine] Job queued: {os.path.basename(safe_input)} -> preset: {preset}"]
                }

            data["input_path"] = safe_input
            t = threading.Thread(target=run_conversion_job, args=(job_id, data))
            t.daemon = True
            t.start()

            self.send_json({"status": "queued", "job_id": job_id})
            return

        elif path == "/api/jobs/cancel":
            job_id = data.get("job_id")
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job:
                    job["cancelled"] = True
                    job["status"] = "cancelled"
                    proc = job.get("proc")
                    if proc:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                    out_path = job.get("output_path")
                    if out_path and os.path.exists(out_path):
                        try:
                            os.remove(out_path)
                        except Exception:
                            pass
                    job["logs"].append("[omni-engine] Process cancelled by user. Partial files cleaned up.")
                    self.send_json({"status": "cancelled"})
                    return
            self.send_json({"status": "not_found"}, status=404)
            return

        elif path == "/api/open-folder":
            raw_target = data.get("path")
            if raw_target:
                safe_target = resolve_safe_path(raw_target)
                if not safe_target:
                    self.send_json({"error": "Path access denied or invalid"}, status=400)
                    return
            else:
                safe_target = OUTPUTS_DIR

            success, resolved_path = reveal_in_file_manager(safe_target)
            if success:
                self.send_json({"status": "opened", "path": resolved_path})
            else:
                self.send_json({"error": resolved_path}, status=500)
            return

        elif path == "/api/shutdown":
            self.send_json({"status": "shutting_down"})
            def do_exit():
                time.sleep(0.5)
                remove_pid_file()
                os._exit(0)
            threading.Thread(target=do_exit, daemon=True).start()
            return

        self.send_response(404)
        self.end_headers()

    def serve_file(self, file_path, mime_type):
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_download(self, file_path, download_name):
        size = os.path.getsize(file_path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        safe_name = download_name.replace('"', '\"')
        encoded_name = urllib.parse.quote(download_name)
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{encoded_name}')
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(file_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, length=65536)

    def serve_video_range(self, file_path):
        size = os.path.getsize(file_path)
        range_header = self.headers.get("Range")
        mime = "video/mp4"
        if file_path.endswith(".webm"): mime = "video/webm"
        elif file_path.endswith(".mkv"): mime = "video/x-matroska"
        elif file_path.endswith(".mp3"): mime = "audio/mpeg"
        elif file_path.endswith(".m4a"): mime = "audio/mp4"
        elif file_path.endswith(".wav"): mime = "audio/wav"
        
        start = 0
        end = size - 1
        is_range = False

        if range_header and range_header.strip().startswith("bytes="):
            raw_range = range_header.strip().replace("bytes=", "").strip()
            parts = raw_range.split("-", 1)
            try:
                if parts[0] == "":
                    # Suffix range: bytes=-500 (last 500 bytes)
                    suffix_len = int(parts[1])
                    start = max(0, size - suffix_len)
                    end = size - 1
                    is_range = True
                elif parts[1] == "":
                    # Prefix range: bytes=500- (from 500 to EOF)
                    start = int(parts[0])
                    end = size - 1
                    is_range = True
                else:
                    # Explicit range: bytes=500-1000
                    start = int(parts[0])
                    end = min(int(parts[1]), size - 1)
                    is_range = True

                if start >= size or start > end or start < 0:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            except Exception:
                is_range = False

        length = end - start + 1

        if is_range:
            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            
            try:
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(remaining, 65536))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (ConnectionResetError, BrokenPipeError):
                pass
        else:
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            try:
                with open(file_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=65536)
            except (ConnectionResetError, BrokenPipeError):
                pass

def start_server(port=5050):
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, OmniRequestHandler)
    print(f"\n=======================================================")
    print(f"  OmniRemux Server running at: http://localhost:{port}")
    print(f"  Drag & Drop videos in your browser to convert!")
    print(f"=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down OmniRemux server...")
        httpd.server_close()

if __name__ == "__main__":
    port = 5050
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except Exception:
            pass
    start_server(port)
