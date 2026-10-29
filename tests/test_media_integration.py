import os
import time
import unittest

import server
from server import probe_file, run_conversion_job, JOBS, JOBS_LOCK, OUTPUTS_DIR

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def require_fixture(test_case, path):
    if not os.path.exists(path):
        if os.environ.get("CI"):
            test_case.fail(f"Required CI fixture missing: {path}")
        else:
            test_case.skipTest(f"Fixture {path} not found")

class TestMediaIntegration(unittest.TestCase):
    def test_mute_conversion_output_has_no_audio(self):
        sample = os.path.join(FIXTURES_DIR, "test_h264_aac.mp4")
        require_fixture(self, sample)

        job_id = f"test_mute_{int(time.time()*1000)}"
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "status": "queued", "progress": 0.0, "logs": []}

        options = {
            "input_path": sample,
            "preset": "telegram_web_mp4",
            "audio_strategy": "mute",
            "custom_filename": "mute_test.mp4"
        }
        run_conversion_job(job_id, options)
        job = JOBS[job_id]

        self.assertEqual(job["status"], "completed", f"Job failed: {job.get('error')}")
        out_path = job["output_path"]
        self.assertTrue(os.path.exists(out_path))

        try:
            probe = probe_file(out_path)
            self.assertIsNotNone(probe)
            self.assertEqual(len(probe["audio_streams"]), 0, "Expected zero audio streams for mute output")
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def test_aac_stereo_conversion_output_streams(self):
        sample = os.path.join(FIXTURES_DIR, "test_hevc_eac3.mkv")
        require_fixture(self, sample)

        job_id = f"test_stereo_{int(time.time()*1000)}"
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "status": "queued", "progress": 0.0, "logs": []}

        options = {
            "input_path": sample,
            "preset": "telegram_web_mp4",
            "audio_strategy": "aac_stereo",
            "custom_filename": "stereo_test.mp4"
        }
        run_conversion_job(job_id, options)
        job = JOBS[job_id]

        self.assertEqual(job["status"], "completed", f"Job failed: {job.get('error')}")
        out_path = job["output_path"]
        self.assertTrue(os.path.exists(out_path))

        try:
            probe = probe_file(out_path)
            self.assertIsNotNone(probe)
            self.assertEqual(len(probe["audio_streams"]), 1)
            a_stream = probe["audio_streams"][0]
            self.assertEqual(a_stream["codec"].lower(), "aac")
            self.assertEqual(a_stream["channels"], 2)
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def test_gif_conversion_output_properties(self):
        sample = os.path.join(FIXTURES_DIR, "test_h264_aac.mp4")
        require_fixture(self, sample)

        job_id = f"test_gif_{int(time.time()*1000)}"
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "status": "queued", "progress": 0.0, "logs": []}

        options = {
            "input_path": sample,
            "preset": "gif",
            "custom_filename": "anim_test.gif"
        }
        run_conversion_job(job_id, options)
        job = JOBS[job_id]

        self.assertEqual(job["status"], "completed", f"Job failed: {job.get('error')}")
        out_path = job["output_path"]
        self.assertTrue(os.path.exists(out_path))

        try:
            probe = probe_file(out_path)
            self.assertIsNotNone(probe)
            self.assertEqual(len(probe["audio_streams"]), 0)
            self.assertEqual(len(probe["video_streams"]), 1)
            self.assertIn("gif", probe["container"].lower())
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

if __name__ == "__main__":
    unittest.main()
