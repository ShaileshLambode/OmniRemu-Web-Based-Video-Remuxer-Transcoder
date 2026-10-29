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
    reserve_unique_output_path,
    release_output_reservation,
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
        temp_dir = os.path.realpath(tempfile.mkdtemp(dir=APP_DIR))
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
        temp_dir = os.path.realpath(tempfile.mkdtemp())
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

    def test_reserve_unique_output_path_concurrent(self):
        import concurrent.futures
        temp_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            results = []
            def reserve_worker():
                return reserve_unique_output_path("race_test", ".mp4", temp_dir)

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(reserve_worker) for _ in range(15)]
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())

            filenames = [r[0] for r in results]
            paths = [r[1] for r in results]

            # Every concurrent call must receive a distinct filename and path
            self.assertEqual(len(filenames), 15)
            self.assertEqual(len(set(filenames)), 15)
            self.assertEqual(len(set(paths)), 15)

            # Release all reservations
            for p in paths:
                release_output_reservation(p)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_reserve_unique_output_path_confinement(self):
        temp_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            # Traversal attempts in custom filename must be stripped to basenames and confined
            fname, path = reserve_unique_output_path("../../evil_traversal", ".mp4", temp_dir)
            self.assertTrue(os.path.commonpath([temp_dir, path]) == temp_dir)
            self.assertEqual(fname, "evil_traversal_converted.mp4")
            release_output_reservation(path)

            fname_unc, path_unc = reserve_unique_output_path(r"\\192.168.1.1\share\exploit", ".mp4", temp_dir)
            self.assertTrue(os.path.commonpath([temp_dir, path_unc]) == temp_dir)
            self.assertEqual(fname_unc, "exploit_converted.mp4")
            release_output_reservation(path_unc)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
