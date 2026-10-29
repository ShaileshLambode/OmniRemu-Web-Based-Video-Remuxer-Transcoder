import os
import re
import unittest

STATIC_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html")

class TestFrontendHandlers(unittest.TestCase):
    def setUp(self):
        with open(STATIC_HTML_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_open_outputs_folder_handler_checks_status_and_errors(self):
        # Find openOutputsFolderBtn block
        idx = self.content.find('openOutputsFolderBtn.addEventListener("click"')
        self.assertNotEqual(idx, -1, "openOutputsFolderBtn listener must exist")
        block = self.content[idx:idx+1500]

        # Verify POST method and session token
        self.assertIn('method: "POST"', block)
        self.assertIn('"X-Omni-Token": sessionToken', block)

        # Verify response checking: res.ok and data.status === "opened"
        self.assertTrue(
            "res.ok && data.status === \"opened\"" in block or
            "res.ok" in block and "status === \"opened\"" in block,
            "Handler must check res.ok and data.status === 'opened'"
        )

        # Verify error handling for both API failure (else) and exception (catch)
        self.assertIn("Failed", block)
        self.assertIn("catch", block)
        self.assertIn("Error", block)

        # Verify button restore
        self.assertIn("setTimeout", block)

    def test_open_folder_job_handler_checks_status_and_errors(self):
        idx = self.content.find('openFolderBtn.onclick = async () =>')
        self.assertNotEqual(idx, -1, "openFolderBtn onclick must exist")
        block = self.content[idx:idx+1500]

        self.assertIn('method: "POST"', block)
        self.assertIn('"X-Omni-Token": sessionToken', block)
        self.assertTrue("res.ok && data.status === \"opened\"" in block)
        self.assertIn("Failed", block)
        self.assertIn("catch", block)
        self.assertIn("Error", block)
        self.assertIn("setTimeout", block)

if __name__ == "__main__":
    unittest.main()
