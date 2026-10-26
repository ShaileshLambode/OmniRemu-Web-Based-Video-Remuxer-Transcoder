import os
import sys
import json
import time
import uuid
import shutil
import urllib.parse
import subprocess
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Base Directories
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
UPLOADS_DIR = os.path.join(APP_DIR, "uploads")
OUTPUTS_DIR = os.path.join(APP_DIR, "outputs")
THUMBS_DIR = os.path.join(APP_DIR, "thumbs")
WORKSPACE_DIR = os.path.dirname(APP_DIR)

for d in [STATIC_DIR, UPLOADS_DIR, OUTPUTS_DIR, THUMBS_DIR]:
    os.makedirs(d, exist_ok=True)

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
                    "fps": eval(s.get("r_frame_rate", "24/1")) if "/" in s.get("r_frame_rate", "") else 24,
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

def run_conversion_job(job_id, options):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return
        
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
        
    output_filename = f"{base_name}_converted{ext}"
    output_path = os.path.join(OUTPUTS_DIR, output_filename)
    
    # Check if user specified audio strategy, resolution, etc.
    audio_strategy = options.get("audio_strategy", "auto")
    resolution = options.get("resolution", "original")
    crf = options.get("crf", 18)
    faststart = options.get("faststart", True)
    trim_start = options.get("trim_start")
    trim_end = options.get("trim_end")
    
    # Find primary video stream & aac audio stream
    v_idx = 0
    aac_idx = None
    first_a_idx = None
    if probe_info:
        if probe_info.get("video_streams"):
            v_idx = probe_info["video_streams"][0]["index"]
        for a in probe_info.get("audio_streams", []):
            if first_a_idx is None:
                first_a_idx = a["index"]
            if a.get("is_aac") and aac_idx is None:
                aac_idx = a["index"]
                
    cmd = ["ffmpeg", "-y"]
    
    # Trim parameters before input for fast seek
    if trim_start and trim_start.strip():
        cmd.extend(["-ss", trim_start.strip()])
    if trim_end and trim_end.strip():
        cmd.extend(["-to", trim_end.strip()])
        
    cmd.extend(["-i", input_path])
    
    # Command Construction by Preset
    if preset == "telegram_web_mp4":
        # Zero loss stream remuxing with audio compatibility check
        cmd.extend(["-map", f"0:{v_idx}"])
        if aac_idx is not None and audio_strategy in ["auto", "copy"]:
            cmd.extend(["-map", f"0:{aac_idx}", "-c", "copy"])
        elif first_a_idx is not None:
            cmd.extend(["-map", f"0:{first_a_idx}", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k"])
        else:
            cmd.extend(["-c:v", "copy"])
            
        if faststart:
            cmd.extend(["-movflags", "+faststart"])
            
    elif preset == "universal_mp4":
        # High compatibility H.264 + AAC
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
        if first_a_idx is not None:
            cmd.extend(["-map", f"0:{first_a_idx}", "-c:a", "aac", "-b:a", "192k"])
        if faststart:
            cmd.extend(["-movflags", "+faststart"])
            
    elif preset == "webm":
        cmd.extend(["-map", f"0:{v_idx}", "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0"])
        if first_a_idx is not None:
            cmd.extend(["-map", f"0:{first_a_idx}", "-c:a", "libopus", "-b:a", "128k"])
            
    elif preset in ["audio_mp3", "audio_aac", "audio_wav"]:
        cmd.extend(["-vn"])
        if first_a_idx is not None:
            cmd.extend(["-map", f"0:{first_a_idx}"])
        if preset == "audio_mp3":
            cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
        elif preset == "audio_aac":
            cmd.extend(["-c:a", "aac", "-b:a", "256k"])
        elif preset == "audio_wav":
            cmd.extend(["-c:a", "pcm_s16le"])
            
    elif preset == "gif":
        cmd.extend(["-vf", "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"])
        
    cmd.extend(["-progress", "pipe:1", output_path])
    
    log_cmd_str = " ".join([f'"{x}"' if " " in x else x for x in cmd])
    
    with JOBS_LOCK:
        job["status"] = "processing"
        job["start_time"] = time.time()
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
                            if total_duration > 0:
                                job["progress"] = min(99.5, round((cur_time / total_duration) * 100, 1))
                                elapsed = time.time() - job["start_time"]
                                if cur_time > 0 and elapsed > 0:
                                    eta = (total_duration - cur_time) / (cur_time / elapsed)
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
            if proc.returncode == 0 and out_exists:
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
                
    except Exception as e:
        with JOBS_LOCK:
            job["status"] = "failed"
            job["error"] = str(e)
            job["logs"].append(f"[omni-engine] EXCEPTION: {e}")

def reveal_in_file_manager(target_path=None):
    """
    Reveals the target file in Windows Explorer (or system file manager),
    highlighting the file if it exists, or opening the folder.
    Handles spaces and special characters robustly across Windows, macOS, and Linux.
    """
    if not target_path or not str(target_path).strip():
        target_path = OUTPUTS_DIR

    target_path = os.path.normpath(os.path.abspath(target_path))

    # If the file does not exist at target_path, check inside OUTPUTS_DIR
    if not os.path.exists(target_path):
        alt_path = os.path.join(OUTPUTS_DIR, os.path.basename(target_path))
        if os.path.exists(alt_path):
            target_path = alt_path
        else:
            target_path = OUTPUTS_DIR

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
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
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
                self.serve_file(file_path, "text/html; charset=utf-8")
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
            # Scan workspace for video files
            files_found = []
            for root, dirs, files in os.walk(WORKSPACE_DIR):
                # skip git and app dirs
                if "omni-remux" in root or ".git" in root or ".agents" in root:
                    continue
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in [".mkv", ".mp4", ".mov", ".avi", ".webm", ".ts", ".m2ts"]:
                        full = os.path.join(root, f)
                        try:
                            stat = os.stat(full)
                            files_found.append({
                                "filename": f,
                                "path": full,
                                "rel_path": os.path.relpath(full, WORKSPACE_DIR),
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
            if os.path.exists(thumb_path):
                self.serve_file(thumb_path, "image/jpeg")
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/api/preview/"):
            fname = os.path.basename(path.replace("/api/preview/", ""))
            fpath = os.path.join(OUTPUTS_DIR, fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(UPLOADS_DIR, fname)
            if os.path.exists(fpath):
                self.serve_video_range(fpath)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/api/download/"):
            fname = os.path.basename(path.replace("/api/download/", ""))
            fpath = os.path.join(OUTPUTS_DIR, fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(UPLOADS_DIR, fname)
            if os.path.exists(fpath):
                self.serve_download(fpath, fname)
            else:
                self.send_response(404)
                self.end_headers()
            return

        elif path.startswith("/static/"):
            rel_file = path.replace("/static/", "")
            full = os.path.join(STATIC_DIR, rel_file)
            if os.path.exists(full) and os.path.isfile(full):
                mime = "text/plain"
                if full.endswith(".html"): mime = "text/html"
                elif full.endswith(".css"): mime = "text/css"
                elif full.endswith(".js"): mime = "application/javascript"
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            # Stream directly to uploads dir to handle gigabyte files
            filename = self.headers.get("X-File-Name")
            if filename:
                filename = urllib.parse.unquote(filename)
            else:
                filename = f"upload_{uuid.uuid4().hex[:8]}.mkv"
                
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
            dest_path = os.path.join(UPLOADS_DIR, safe_filename)
            
            content_length = int(self.headers.get("Content-Length", 0))
            
            remaining = content_length
            with open(dest_path, "wb") as f:
                while remaining > 0:
                    chunk_size = min(remaining, 65536)
                    chunk = self.rfile.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
                    
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
            target_path = data.get("path")
            if not target_path and data.get("filename"):
                target_path = os.path.join(UPLOADS_DIR, data.get("filename"))
            if not target_path or not os.path.exists(target_path):
                self.send_json({"error": "File does not exist"}, status=400)
                return
            probe_result = probe_file(target_path)
            if probe_result:
                self.send_json(probe_result)
            else:
                self.send_json({"error": "Failed to probe file"}, status=500)
            return

        elif path == "/api/convert":
            input_path = data.get("path")
            if not input_path and data.get("filename"):
                input_path = os.path.join(UPLOADS_DIR, data.get("filename"))
                
            if not input_path or not os.path.exists(input_path):
                self.send_json({"error": "Input file not found"}, status=400)
                return
                
            job_id = uuid.uuid4().hex[:12]
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "id": job_id,
                    "input_path": input_path,
                    "filename": os.path.basename(input_path),
                    "preset": data.get("preset", "telegram_web_mp4"),
                    "status": "queued",
                    "progress": 0.0,
                    "fps": 0,
                    "speed": "0x",
                    "eta": 0,
                    "processed_bytes": 0,
                    "processed_formatted": "0 B",
                    "output_filename": None,
                    "output_path": None,
                    "logs": [f"[omni-engine] Job queued: {os.path.basename(input_path)} -> preset: {data.get('preset')}"]
                }
                
            data["input_path"] = input_path
            t = threading.Thread(target=run_conversion_job, args=(job_id, data))
            t.daemon = True
            t.start()
            
            self.send_json({"status": "queued", "job_id": job_id})
            return

        elif path == "/api/jobs/cancel":
            job_id = data.get("job_id")
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job and job.get("proc"):
                    try:
                        job["proc"].terminate()
                        job["status"] = "cancelled"
                        job["logs"].append("[omni-engine] Process cancelled by user.")
                        self.send_json({"status": "cancelled"})
                        return
                    except Exception as e:
                        self.send_json({"error": str(e)}, status=500)
                        return
            self.send_json({"status": "not_found"}, status=404)
            return

        elif path == "/api/open-folder":
            target_path = data.get("path")
            success, resolved_path = reveal_in_file_manager(target_path)
            if success:
                self.send_json({"status": "opened", "path": resolved_path})
            else:
                self.send_json({"error": resolved_path}, status=500)
            return

        elif path == "/api/shutdown":
            self.send_json({"status": "shutting_down"})
            def do_exit():
                time.sleep(0.5)
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
        
        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else size - 1
            length = end - start + 1
            
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
