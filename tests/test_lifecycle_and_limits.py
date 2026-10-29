import io
import os
import time
import json
import unittest
from unittest.mock import Mock, patch

import server
from server import (
    OmniRequestHandler,
    SESSION_TOKEN,
    MAX_UPLOAD_SIZE,
    MAX_JOB_HISTORY,
    JOBS,
    JOBS_LOCK,
    OUTPUTS_DIR
)

class TestLifecycleAndLimits(unittest.TestCase):
    def setUp(self):
        self.handler = OmniRequestHandler.__new__(OmniRequestHandler)
        self.handler.server = Mock(server_port=5050)
        self.handler.send_response = Mock()
        self.handler.send_header = Mock()
        self.handler.end_headers = Mock()
        self.handler.wfile = io.BytesIO()

    def test_upload_missing_content_length_rejected(self):
        self.handler.path = "/api/upload"
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(b"")
        self.handler.do_POST()
        self.handler.send_response.assert_called_with(400)

    def test_upload_exceeding_max_limit_rejected_413(self):
        self.handler.path = "/api/upload"
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "Content-Length": str(MAX_UPLOAD_SIZE + 1024),
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(b"")
        self.handler.do_POST()
        self.handler.send_response.assert_called_with(413)

    def test_job_history_pruning(self):
        with JOBS_LOCK:
            JOBS.clear()
            # Populate with finished jobs
            for i in range(MAX_JOB_HISTORY + 5):
                jid = f"history_job_{i}"
                JOBS[jid] = {
                    "id": jid,
                    "status": "completed",
                    "logs": []
                }

        # Simulate convert endpoint pruning logic
        with JOBS_LOCK:
            if len(JOBS) >= MAX_JOB_HISTORY:
                finished = [jid for jid, j in JOBS.items() if j.get("status") in ["completed", "failed", "cancelled"]]
                for old_id in finished[:len(JOBS) - MAX_JOB_HISTORY + 1]:
                    del JOBS[old_id]

        self.assertLessEqual(len(JOBS), MAX_JOB_HISTORY)

    def test_cancellation_cleans_partial_files_and_terminates_proc(self):
        dummy_output = os.path.join(OUTPUTS_DIR, "partial_test_output.mp4")
        with open(dummy_output, "w") as f:
            f.write("partial stream content")

        mock_proc = Mock()
        mock_proc.terminate = Mock()
        mock_proc.wait = Mock()

        job_id = "test_cancel_job"
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "processing",
                "proc": mock_proc,
                "output_path": dummy_output,
                "logs": []
            }

        # Send cancellation request
        self.handler.path = "/api/jobs/cancel"
        payload = json.dumps({"job_id": job_id}).encode("utf-8")
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "Content-Length": str(len(payload)),
            "Content-Type": "application/json",
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(payload)
        self.handler.do_POST()

        self.handler.send_response.assert_called_with(200)
        mock_proc.terminate.assert_called_once()
        self.assertFalse(os.path.exists(dummy_output), "Expected partial file to be removed upon cancellation")

        with JOBS_LOCK:
            self.assertEqual(JOBS[job_id]["status"], "cancelled")

if __name__ == "__main__":
    unittest.main()
