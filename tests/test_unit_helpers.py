import os
import unittest
import tempfile
import shutil
from server import (
    parse_fps,
    parse_time_str,
    format_seconds,
    format_bytes,
    sanitize_filename,
    resolve_safe_path,
    get_unique_output_path,
    APP_DIR,
)

class TestUnitHelpers(unittest.TestCase):
    def test_parse_fps_valid(self):
        self.assertEqual(parse_fps("24/1"), 24.0)
        self.assertEqual(parse_fps("60/1"), 60.0)
        self.assertEqual(parse_fps("25"), 25.0)
        self.assertAlmostEqual(parse_fps("30000/1001"), 29.97002997, places=4)

    def test_parse_fps_edge_cases(self):
        # 0/0, 0/1, negative, and invalid should safely fallback to 24.0 without ZeroDivisionError
        self.assertEqual(parse_fps("0/0"), 24.0)
        self.assertEqual(parse_fps("0/1"), 24.0)
        self.assertEqual(parse_fps(""), 24.0)
        self.assertEqual(parse_fps(None), 24.0)
        self.assertEqual(parse_fps("invalid/text"), 24.0)
        self.assertEqual(parse_fps("1/2/3"), 24.0)
        self.assertEqual(parse_fps("-10/1"), 24.0)
        self.assertEqual(parse_fps("-25"), 24.0)

    def test_parse_time_str(self):
        self.assertEqual(parse_time_str("01:23:45"), 5025.0)
        self.assertEqual(parse_time_str("02:15"), 135.0)
        self.assertEqual(parse_time_str("45"), 45.0)
        self.assertEqual(parse_time_str("00:00:10.5"), 10.5)
        self.assertEqual(parse_time_str(""), 0.0)
        self.assertEqual(parse_time_str(None), 0.0)
        self.assertEqual(parse_time_str("invalid_time"), 0.0)

    def test_format_seconds(self):
        self.assertEqual(format_seconds(5025), "01:23:45")
        self.assertEqual(format_seconds(135), "02:15")
        self.assertEqual(format_seconds(45), "00:45")
        self.assertEqual(format_seconds(0), "00:00")

    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500.0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1048576), "1.0 MB")
        self.assertEqual(format_bytes(1073741824), "1.0 GB")

    def test_sanitize_filename(self):
        # Preserves brackets, dashes, underscores, and unicode
        name1 = "[Anime-Raws] Show - 01 (1080p).mkv"
        self.assertEqual(sanitize_filename(name1), name1)

        name_unicode = "進撃の巨人_Final (Season 4).mp4"
        self.assertEqual(sanitize_filename(name_unicode), name_unicode)

        # Strips dangerous characters
        self.assertEqual(sanitize_filename('evil"file|name*?.mkv'), "evilfilename.mkv")

        # Strips path separators and directory components
        self.assertEqual(sanitize_filename("inject;rm -rf /whoami.mp4"), "whoami.mp4")
        self.assertEqual(sanitize_filename("../../../etc/passwd.mp4"), "passwd.mp4")
        self.assertEqual(sanitize_filename(r"..\..\Windows\system32.dll"), "system32.dll")

        # Strips leading/trailing periods and spaces
        self.assertEqual(sanitize_filename("...hidden_file.mp4"), "hidden_file.mp4")

        # Empty fallback
        fallback = sanitize_filename("???:::***", default_ext=".mkv")
        self.assertTrue(fallback.endswith(".mkv"))
        self.assertTrue(fallback.startswith("upload_"))

    def test_resolve_safe_path(self):
        # Create a temp directory inside workspace for safe isolation
        temp_dir = tempfile.mkdtemp(dir=APP_DIR)
        try:
            sample_file = os.path.join(temp_dir, "sample.mp4")
            with open(sample_file, "w") as f:
                f.write("test")

            # Valid file inside APP_DIR
            resolved = resolve_safe_path(sample_file)
            self.assertIsNotNone(resolved)
            self.assertEqual(os.path.realpath(sample_file), resolved)

            # Traversal attacks outside APP_DIR
            self.assertIsNone(resolve_safe_path("../../windows/system32/cmd.exe"))
            self.assertIsNone(resolve_safe_path("/etc/passwd"))
            self.assertIsNone(resolve_safe_path("../../../../../../../../../windows/explorer.exe"))

            # UNC network path attacks
            self.assertIsNone(resolve_safe_path(r"\\192.168.1.1\share\payload.mp4"))
            self.assertIsNone(resolve_safe_path("//attacker.com/share/payload.mp4"))

            # Non-existent file
            self.assertIsNone(resolve_safe_path(os.path.join(temp_dir, "does_not_exist.mp4")))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_unique_output_path(self):
        temp_dir = tempfile.mkdtemp()
        try:
            fname, path = get_unique_output_path("test_video", ".mp4", temp_dir)
            self.assertEqual(fname, "test_video_converted.mp4")
            self.assertEqual(path, os.path.join(temp_dir, "test_video_converted.mp4"))

            # Create existing file
            with open(path, "w") as f:
                f.write("dummy")

            fname2, path2 = get_unique_output_path("test_video", ".mp4", temp_dir)
            self.assertEqual(fname2, "test_video_converted (1).mp4")
            self.assertEqual(path2, os.path.join(temp_dir, "test_video_converted (1).mp4"))

            with open(path2, "w") as f:
                f.write("dummy 2")

            fname3, path3 = get_unique_output_path("test_video", ".mp4", temp_dir)
            self.assertEqual(fname3, "test_video_converted (2).mp4")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
