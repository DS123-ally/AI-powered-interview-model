import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from question_generator import questionGenerator


class QuestionGenerationTests(unittest.TestCase):
    def test_compact_prompt_and_local_answer_times(self):
        generator = questionGenerator()
        prompt = generator._build_prompt("Python developer " * 100, "Build APIs with MongoDB " * 100, "Candidate", 3)
        self.assertLess(len(prompt), 1800)
        self.assertIn("exactly 3", prompt)

        response = {
            "questions": [
                "Tell me about your background?",
                "How do you handle a production API failure?",
                "Describe a time you resolved a team conflict?",
            ]
        }
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"message": {"content": json.dumps(response)}}

        with patch("question_generator.requests.post", return_value=FakeResponse()) as post:
            first = generator.generate("Python developer", "Build APIs with MongoDB", "Candidate")
            second = generator.generate("Python developer", "Build APIs with MongoDB", "Candidate")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["generation_method"], "ai-ollama")
        self.assertEqual(first["timings_ms"], [90000, 75000, 90000])
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["num_predict"], 192)
        self.assertEqual(payload["keep_alive"], "15m")


if __name__ == "__main__":
    unittest.main()
