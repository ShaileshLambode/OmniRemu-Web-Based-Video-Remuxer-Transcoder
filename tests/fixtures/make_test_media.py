import os
import subprocess
import sys

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))

def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        return False
    return True

def generate_fixtures(output_dir=None):
    target_dir = output_dir or FIXTURES_DIR
    os.makedirs(target_dir, exist_ok=True)
    
    files = {
        "test_h264_aac.mp4": [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            os.path.join(target_dir, "test_h264_aac.mp4")
        ],
        "test_hevc_eac3.mkv": [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=500:duration=2",
            "-c:v", "libx265", "-pix_fmt", "yuv420p",
            "-c:a", "eac3", "-b:a", "384k", "-ac", "6",
            os.path.join(target_dir, "test_hevc_eac3.mkv")
        ],
        "test_dual_audio.mkv": [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=400:duration=2",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a:0", "aac", "-metadata:s:a:0", "language=eng",
            "-c:a:1", "ac3", "-metadata:s:a:1", "language=hin",
            os.path.join(target_dir, "test_dual_audio.mkv")
        ],
        "test_audio_only.mp3": [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
            "-c:a", "libmp3lame", "-b:a", "192k",
            os.path.join(target_dir, "test_audio_only.mp3")
        ]
    }
    
    generated = {}
    failed = []
    for filename, cmd in files.items():
        out_path = os.path.join(target_dir, filename)
        if not os.path.exists(out_path):
            print(f"Generating fixture: {filename}...")
            ok = run_cmd(cmd)
            if ok:
                generated[filename] = out_path
            else:
                failed.append(filename)
        else:
            generated[filename] = out_path
            
    if failed:
        print(f"ERROR: Failed to generate required fixtures: {failed}", file=sys.stderr)
        return generated, False
    return generated, True

if __name__ == "__main__":
    out, ok = generate_fixtures()
    print("Fixtures ready:", list(out.keys()))
    if not ok:
        sys.exit(1)
