import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import server
from server import reveal_in_file_manager, OUTPUTS_DIR, APP_DIR

class TestFileManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(dir=APP_DIR)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_target_is_outputs_dir(self):
        with patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(None)
            self.assertTrue(ok)
            self.assertEqual(path, os.path.normpath(os.path.abspath(OUTPUTS_DIR)))

    def test_empty_string_target_is_outputs_dir(self):
        with patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager("   ")
            self.assertTrue(ok)
            self.assertEqual(path, os.path.normpath(os.path.abspath(OUTPUTS_DIR)))

    def test_missing_file_falls_back_to_outputs_dir(self):
        with patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager("completely_nonexistent_file_12345.mp4")
            self.assertTrue(ok)
            self.assertEqual(path, os.path.normpath(os.path.abspath(OUTPUTS_DIR)))

    def test_existing_file_in_outputs_dir(self):
        test_file = os.path.join(OUTPUTS_DIR, "file_manager_test.mp4")
        with open(test_file, "w") as f:
            f.write("dummy")
        try:
            with patch("subprocess.Popen") as mock_popen:
                ok, path = reveal_in_file_manager(test_file)
                self.assertTrue(ok)
                if sys.platform in ["win32", "darwin"]:
                    self.assertEqual(path, os.path.normpath(os.path.abspath(test_file)))
                else:
                    # Linux xdg-open opens the parent folder
                    self.assertEqual(path, os.path.normpath(os.path.abspath(OUTPUTS_DIR)))
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_windows_file_select_command_format(self):
        test_file = os.path.join(self.temp_dir, "video file with spaces.mp4")
        with open(test_file, "w") as f:
            f.write("test")

        with patch("sys.platform", "win32"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(test_file)
            self.assertTrue(ok)
            expected_cmd = f'explorer.exe /select,"{os.path.normpath(os.path.abspath(test_file))}"'
            mock_popen.assert_called_with(expected_cmd)

    def test_windows_folder_command_format(self):
        with patch("sys.platform", "win32"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(self.temp_dir)
            self.assertTrue(ok)
            expected_cmd = f'explorer.exe "{os.path.normpath(os.path.abspath(self.temp_dir))}"'
            mock_popen.assert_called_with(expected_cmd)

    def test_windows_unicode_filename(self):
        test_file = os.path.join(self.temp_dir, "鬼滅の刃_無限列車.mkv")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("unicode test")

        with patch("sys.platform", "win32"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(test_file)
            self.assertTrue(ok)
            expected_cmd = f'explorer.exe /select,"{os.path.normpath(os.path.abspath(test_file))}"'
            mock_popen.assert_called_with(expected_cmd)

    def test_macos_file_command_format(self):
        test_file = os.path.join(self.temp_dir, "sample.mp4")
        with open(test_file, "w") as f:
            f.write("test")

        with patch("sys.platform", "darwin"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(test_file)
            self.assertTrue(ok)
            mock_popen.assert_called_with(["open", "-R", os.path.normpath(os.path.abspath(test_file))])

    def test_macos_directory_command_format(self):
        with patch("sys.platform", "darwin"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(self.temp_dir)
            self.assertTrue(ok)
            mock_popen.assert_called_with(["open", os.path.normpath(os.path.abspath(self.temp_dir))])

    def test_linux_command_format(self):
        test_file = os.path.join(self.temp_dir, "sample.mp4")
        with open(test_file, "w") as f:
            f.write("test")

        with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(test_file)
            self.assertTrue(ok)
            parent_dir = os.path.dirname(os.path.normpath(os.path.abspath(test_file)))
            mock_popen.assert_called_with(["xdg-open", parent_dir])

    def test_linux_directory_command_format(self):
        with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
            ok, path = reveal_in_file_manager(self.temp_dir)
            self.assertTrue(ok)
            mock_popen.assert_called_with(["xdg-open", os.path.normpath(os.path.abspath(self.temp_dir))])

    def test_launch_failure_handling(self):
        with patch("sys.platform", "linux"), patch("subprocess.Popen", side_effect=OSError("xdg-open not found")):
            ok, err = reveal_in_file_manager(self.temp_dir)
            self.assertFalse(ok)
            self.assertIn("xdg-open not found", err)

if __name__ == "__main__":
    unittest.main()
