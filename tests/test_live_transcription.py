import sys
import unittest
from pathlib import Path

import numpy as np
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main


class LiveTranscriptionTests(unittest.TestCase):
    def test_resamples_pcm_and_returns_whisper_text(self):
        original = main.transcribe_live_with_whisper
        captured = []
        try:
            def fake_transcribe(samples):
                captured.append(samples)
                return {"text": "  Hello from Whisper  "}

            main.transcribe_live_with_whisper = fake_transcribe
            audio = np.full(48000 * 5, 0.1, dtype="<f4")
            result = main.transcribe_live(audio.tobytes(), sample_rate=48000)
            self.assertEqual(result, {"text": "Hello from Whisper"})
            self.assertEqual(len(captured[0]), 16000 * 5)
        finally:
            main.transcribe_live_with_whisper = original

    def test_rejects_invalid_pcm(self):
        with self.assertRaises(HTTPException) as error:
            main.transcribe_live(b"bad", sample_rate=16000)
        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
