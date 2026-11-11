import os
import sys
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot import get_whisper_model, transcribe_audio_file


class TestVoiceNoteTranscription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_audio_path = Path("/tmp/test_voice_unit.oga")
        # Generate a short 1-second audio tone using ffmpeg
        os.system(f"/opt/homebrew/bin/ffmpeg -f lavfi -i 'sine=frequency=440:duration=1' -c:a libopus {cls.test_audio_path} -y >/dev/null 2>&1")

    @classmethod
    def tearDownClass(cls):
        if cls.test_audio_path.exists():
            cls.test_audio_path.unlink()

    def test_whisper_model_singleton(self):
        """Verify get_whisper_model returns a valid cached WhisperModel instance."""
        model1 = get_whisper_model("base")
        model2 = get_whisper_model("base")
        self.assertIsNotNone(model1)
        self.assertIs(model1, model2)

    def test_transcribe_audio_file_no_crash(self):
        """Verify transcribe_audio_file processes .oga audio without crashing."""
        self.assertTrue(self.test_audio_path.exists())
        text = transcribe_audio_file(self.test_audio_path)
        # Sine wave tone should produce empty or minimal text without crashing
        self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
