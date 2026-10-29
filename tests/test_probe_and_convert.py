import os
import unittest
import tempfile
import shutil
import time
from server import probe_file, run_conversion_job, JOBS, JOBS_LOCK, OUTPUTS_DIR

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestProbeAndConvert(unittest.TestCase):
    def test_probe_h264_aac(self):
        sample = os.path.join(FIXTURES_DIR, "test_h264_aac.mp4")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        info = probe_file(sample)
        self.assertIsNotNone(info)
        self.assertIn("mp4", info["container"].lower())
        self.assertGreater(info["duration"], 0)
        self.assertEqual(len(info["video_streams"]), 1)
        self.assertEqual(info["video_streams"][0]["codec"].lower(), "h264")
        self.assertEqual(len(info["audio_streams"]), 1)
        self.assertEqual(info["audio_streams"][0]["codec"].lower(), "aac")
        self.assertTrue(info["audio_streams"][0]["is_aac"])

    def test_probe_hevc_eac3(self):
        sample = os.path.join(FIXTURES_DIR, "test_hevc_eac3.mkv")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        info = probe_file(sample)
        self.assertIsNotNone(info)
        self.assertIn("matroska", info["container"].lower())
        self.assertEqual(len(info["video_streams"]), 1)
        self.assertEqual(info["video_streams"][0]["codec"].lower(), "hevc")
        self.assertEqual(len(info["audio_streams"]), 1)
        self.assertEqual(info["audio_streams"][0]["codec"].lower(), "eac3")
        self.assertFalse(info["audio_streams"][0]["is_aac"])

    def test_probe_dual_audio(self):
        sample = os.path.join(FIXTURES_DIR, "test_dual_audio.mkv")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        info = probe_file(sample)
        self.assertIsNotNone(info)
        self.assertEqual(len(info["audio_streams"]), 2)
        codecs = [a["codec"].lower() for a in info["audio_streams"]]
        self.assertIn("ac3", codecs)
        self.assertIn("aac", codecs)

    def test_probe_audio_only(self):
        sample = os.path.join(FIXTURES_DIR, "test_audio_only.mp3")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        info = probe_file(sample)
        self.assertIsNotNone(info)
        self.assertEqual(len(info["video_streams"]), 0)
        self.assertEqual(len(info["audio_streams"]), 1)
        self.assertEqual(info["audio_streams"][0]["codec"].lower(), "mp3")

    def test_fast_remux_execution(self):
        sample = os.path.join(FIXTURES_DIR, "test_h264_aac.mp4")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        job_id = f"test_job_{int(time.time()*1000)}"
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "progress": 0.0,
                "logs": []
            }

        options = {
            "input_path": sample,
            "preset": "telegram_web_mp4",
            "audio_strategy": "auto",
            "resolution": "original",
            "custom_filename": "fast_remux_test.mp4"
        }

        run_conversion_job(job_id, options)

        with JOBS_LOCK:
            job = JOBS.get(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed", f"Job failed: {job.get('error')}")
        self.assertEqual(job["progress"], 100.0)
        self.assertTrue(os.path.exists(job["output_path"]))
        self.assertGreater(job["output_size"], 0)

        # Cleanup test output file
        try:
            os.remove(job["output_path"])
        except Exception:
            pass

    def test_audio_extraction_execution(self):
        sample = os.path.join(FIXTURES_DIR, "test_h264_aac.mp4")
        if not os.path.exists(sample):
            self.skipTest(f"Fixture {sample} not found")

        job_id = f"test_audio_job_{int(time.time()*1000)}"
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "progress": 0.0,
                "logs": []
            }

        options = {
            "input_path": sample,
            "preset": "audio_mp3",
            "custom_filename": "extracted_audio.mp3"
        }

        run_conversion_job(job_id, options)

        with JOBS_LOCK:
            job = JOBS.get(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed", f"Job failed: {job.get('error')}")
        self.assertTrue(os.path.exists(job["output_path"]))

        # Cleanup test output file
        try:
            os.remove(job["output_path"])
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main()
