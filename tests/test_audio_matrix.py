import unittest
from server import build_audio_flags

class TestAudioMatrix(unittest.TestCase):
    def setUp(self):
        self.single_aac_probe = {
            "audio_streams": [
                {"index": 1, "codec": "aac", "is_aac": True, "channels": 2, "sample_rate": "48000"}
            ]
        }
        self.single_eac3_probe = {
            "audio_streams": [
                {"index": 1, "codec": "eac3", "is_aac": False, "channels": 6, "sample_rate": "48000"}
            ]
        }
        self.dual_audio_probe = {
            "audio_streams": [
                {"index": 1, "codec": "ac3", "is_aac": False, "channels": 6, "sample_rate": "48000"},
                {"index": 2, "codec": "aac", "is_aac": True, "channels": 2, "sample_rate": "48000"}
            ]
        }
        self.no_audio_probe = {
            "audio_streams": []
        }

    def test_mute_strategy(self):
        flags = build_audio_flags(self.single_aac_probe, "mute", "telegram_web_mp4")
        self.assertEqual(flags, ["-an"])

    def test_no_audio_probe(self):
        flags = build_audio_flags(self.no_audio_probe, "auto", "telegram_web_mp4")
        self.assertEqual(flags, ["-an"])

    def test_gif_preset(self):
        flags = build_audio_flags(self.single_aac_probe, "auto", "gif")
        self.assertEqual(flags, ["-an"])

    def test_copy_strategy_multi_audio(self):
        flags = build_audio_flags(self.dual_audio_probe, "copy", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-map", "0:2", "-c:a", "copy"])

    def test_aac_stereo_strategy(self):
        flags = build_audio_flags(self.single_eac3_probe, "aac_stereo", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "aac", "-b:a", "256k", "-ac", "2"])

    def test_aac_51_strategy(self):
        flags = build_audio_flags(self.single_eac3_probe, "aac_51", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "aac", "-b:a", "384k", "-ac", "6"])

    def test_telegram_web_mp4_auto_with_aac(self):
        # When AAC is already present, it should direct copy that AAC stream
        flags = build_audio_flags(self.single_aac_probe, "auto", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "copy"])

    def test_telegram_web_mp4_auto_picks_aac_stream(self):
        # In dual audio with AC3 first and AAC second, it picks index 2 (AAC) for direct copy
        flags = build_audio_flags(self.dual_audio_probe, "auto", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:2", "-c:a", "copy"])

    def test_telegram_web_mp4_auto_transcodes_non_aac(self):
        # When only non-AAC (e.g. EAC3) is present, it transcodes to AAC stereo
        flags = build_audio_flags(self.single_eac3_probe, "auto", "telegram_web_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "aac", "-b:a", "256k", "-ac", "2"])

    def test_universal_mp4_auto(self):
        flags = build_audio_flags(self.single_aac_probe, "auto", "universal_mp4")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "aac", "-b:a", "192k", "-ac", "2"])

    def test_webm_auto(self):
        flags = build_audio_flags(self.single_aac_probe, "auto", "webm")
        self.assertEqual(flags, ["-map", "0:1", "-c:a", "libopus", "-b:a", "128k"])

    def test_audio_extraction_presets(self):
        for preset in ["audio_mp3", "audio_aac", "audio_wav"]:
            flags = build_audio_flags(self.dual_audio_probe, "auto", preset)
            self.assertEqual(flags, ["-map", "0:1"])

if __name__ == "__main__":
    unittest.main()
