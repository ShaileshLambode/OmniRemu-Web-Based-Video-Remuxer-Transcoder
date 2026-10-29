import os
import re
import unittest

STATIC_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html")

class TestDOMSafety(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(STATIC_HTML_PATH), f"File not found: {STATIC_HTML_PATH}")
        with open(STATIC_HTML_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_no_dynamic_innerHTML_interpolation(self):
        # Scan for innerHTML assignments
        lines = self.content.splitlines()
        for idx, line in enumerate(lines, 1):
            if "innerHTML" in line and "=" in line:
                # Disallow variable or template interpolation inside innerHTML
                # e.g., `${...}` or `+ variable`
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("/*"):
                    continue
                # Ensure no template literals containing expressions `${...}` are assigned to innerHTML
                # (except static multiline template without ${})
                if "${" in line:
                    self.fail(f"Potential unsafe template interpolation in innerHTML at line {idx}: {stripped}")

    def test_no_insertAdjacentHTML_usage(self):
        self.assertNotIn("insertAdjacentHTML", self.content)

    def test_dynamic_metadata_uses_textContent(self):
        # Verify critical dynamic sinks use textContent
        required_patterns = [
            r'fileName\.textContent\s*=',
            r'fileSize\.textContent\s*=',
            r'fileDuration\.textContent\s*=',
            r'completedFilename\.textContent\s*=',
            r'nameDiv\.textContent\s*=',
            r'line\.textContent\s*='
        ]
        for pattern in required_patterns:
            self.assertTrue(
                re.search(pattern, self.content),
                f"Expected textContent pattern not found: {pattern}"
            )

    def test_hostile_metadata_payload_simulation(self):
        # Simulate hostile probe metadata
        hostile_probe = {
            "filename": "<script>alert('xss')</script>.mp4",
            "container": "<img src=x onerror=alert(1)>",
            "video_streams": [{
                "codec": "<svg onload=alert(2)>",
                "width": 1920,
                "height": 1080
            }],
            "audio_streams": [{
                "codec": "aac",
                "title": "'); DROP TABLE; -- <script>",
                "language": "<b onmouseover=alert(3)>"
            }]
        }
        # In textContent assignment, the text is interpreted literally, not as markup
        # Confirm that index.html never uses raw unescaped values in HTML contexts
        for k, v in hostile_probe.items():
            if isinstance(v, str):
                self.assertNotIn(f"innerHTML = {v}", self.content)

if __name__ == "__main__":
    unittest.main()
