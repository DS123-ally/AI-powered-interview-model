"""
question_generator.py
─────────────────────
Generates tailored interview questions using Ollama (llama3) locally
based on a candidate's qualification and the job description they applied for.

Returns a structured list of questions focused on communication skill assessment
alongside domain-relevant probing questions.

Each question also includes a predicted answer time in milliseconds so the
frontend can use dynamic per-question recording windows instead of a fixed 30s.
"""

import os
import re
import json
import logging
import requests
from functools import lru_cache

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Timing heuristics (fallback when AI doesn't return times)
# ──────────────────────────────────────────────────────────────────
DEFAULT_TIME_MS       = 60_000   # 60 s — generic fallback
MIN_TIME_MS           = 30_000   # 30 s  minimum we ever allow
MAX_TIME_MS           = 180_000  # 3 min maximum we ever allow

COMPLEXITY_RULES = [
    (["tell me about yourself", "background", "introduce"],                   90),
    (["five years", "career goal", "see yourself"],                           60),
    (["strength", "weakness"],                                                60),
    (["describe a time", "situation", "example", "tell me about a time"],    90),
    (["why should we hire", "why are you the best"],                          75),
    (["how do you", "approach", "handle", "manage"],                          75),
    (["what is", "define", "explain", "difference between"],                 45),
    (["why do you want", "why this company", "motivation"],                   60),
    (["technical", "architecture", "design", "system"],                       90),
    (["conflict", "disagreement", "difficult colleague"],                     90),
]


class questionGenerator:
    """
    Uses Ollama's local API (llama3) to generate a personalised set of
    interview questions for a candidate, each paired with a predicted
    answer duration so the frontend can set dynamic recording windows.
    """

    DEFAULT_QUESTION_COUNT = 3

    def __init__(self, api_key=None):
        # Allow overriding model and endpoint via env vars
        self.model = os.getenv("OLLAMA_QUESTION_MODEL") or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434").rstrip('/')
        self.endpoint = f"{base}/api/chat"
        # A cold start on a local CPU can take longer than a cloud request.
        self.timeout = int(os.getenv("OLLAMA_QUESTION_TIMEOUT", "180"))

        logger.info(f"🦙 Ollama question generator initialized using model {self.model} at {self.endpoint}")

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────
    def generate(
        self,
        qualification: str,
        job_description: str,
        candidate_name: str = "",
        question_count: int = DEFAULT_QUESTION_COUNT,
    ) -> dict:
        """
        Generate interview questions with predicted answer timings.

        Returns:
            {
              "questions":       ["Q1", "Q2", ...],
              "timings_ms":      [60000, 90000, ...],
              "generation_method": "ai-ollama" | "fallback",
              "error": "..."   (only present on failure)
            }
        """
        try:
            logger.info(f"🚀 Starting question generation with Ollama (count={question_count}, model={self.model})")
            prompt = self._build_prompt(qualification, job_description, candidate_name, question_count)
            raw    = self._call_api(prompt, question_count)
            logger.info(f"✅ Ollama returned response (length: {len(raw)} chars)")

            parsed    = self._parse_response(raw)
            questions = parsed.get("questions", [])[:question_count]
            timings   = parsed.get("timings_ms", [])[:question_count]

            if not questions:
                logger.warning("Ollama returned no parseable questions — using fallback")
                fallback = self._fallback(qualification, job_description, question_count)
                fallback["error"] = "Ollama returned no usable questions. Check the backend log for the model response."
                return fallback

            timings = self._normalise_timings(timings, questions)

            logger.info(f"✅ AI generated {len(questions)} questions with timings: {timings}")
            return {
                "questions":         questions,
                "timings_ms":        timings,
                "generation_method": "ai-ollama",
            }

        except requests.exceptions.ConnectionError:
            logger.error(f"❌ Connection error: Could not reach Ollama at {self.endpoint}. Is it running?")
            fallback = self._fallback(qualification, job_description, question_count)
            fallback["error"] = "Cannot connect to local Ollama instance."
            return fallback

        except Exception as exc:
            logger.error(f"❌ Question generation failed: {exc}", exc_info=True)
            fallback = self._fallback(qualification, job_description, question_count)
            fallback["error"] = str(exc)
            return fallback

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    def _build_prompt(self, qualification: str, job_description: str,
                      candidate_name: str, question_count: int) -> str:
        def concise(value: str, limit: int) -> str:
            value = " ".join(value.split())
            return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0]

        qualification = concise(qualification, 500)
        job_description = concise(job_description, 900)
        json_questions = ",".join(f'"question {index + 1}?"' for index in range(question_count))
        return (
            f"Write exactly {question_count} concise, open-ended interview questions. "
            "Two must test skills for the job; one must ask for a specific past situation. "
            "Ask questions that reveal clear communication. Each question must be at most 18 words. "
            f"Return only JSON: {{\"questions\":[{json_questions}]}}. "
            f"Qualification: {qualification}. Job: {job_description}."
        )

    @lru_cache(maxsize=128)
    def _call_api(self, prompt: str, question_count: int) -> str:
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": max(192, question_count * 55),
            },
            "keep_alive": "15m",
        }

        resp = requests.post(
            self.endpoint, headers=headers, json=payload,
            timeout=self.timeout
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama API returned {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data.get("message", {}).get("content", "").strip()
        logger.info(
            "Ollama questions: %d chars, load %.1fs, prompt %.1fs, output %.1fs (%s tokens)",
            len(content), data.get("load_duration", 0) / 1e9,
            data.get("prompt_eval_duration", 0) / 1e9,
            data.get("eval_duration", 0) / 1e9, data.get("eval_count", "unknown"),
        )
        return content

    def _parse_response(self, raw: str) -> dict:
        """
        Parse the AI response. Handles:
        - Clean JSON object  {"questions": [...], "predicted_seconds": [...]}
        - JSON wrapped in ```json ... ```
        - Fallback: extract question-looking lines + use heuristic timing
        """
        clean = re.sub(r"```*(?:json)?", "", raw).strip().rstrip("`").strip()

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                raw_questions = parsed.get("questions", [])
                questions = [q.strip() for q in raw_questions if isinstance(q, str) and q.strip()] if isinstance(raw_questions, list) else []
                seconds = parsed.get("predicted_seconds", [])
                timings_ms = []
                if isinstance(seconds, list):
                    for value in seconds:
                        try:
                            timings_ms.append(int(float(value) * 1000))
                        except (TypeError, ValueError):
                            timings_ms.append(DEFAULT_TIME_MS)
                return {"questions": questions, "timings_ms": timings_ms}

            if isinstance(parsed, list):
                questions = [str(q).strip() for q in parsed if str(q).strip()]
                return {"questions": questions, "timings_ms": []}

        except json.JSONDecodeError:
            pass

        # Last resort: extract question lines
        questions = []
        for line in clean.splitlines():
            line = re.sub(r"^[\d]+[.)]\s*", "", line).strip()
            line = re.sub(r"^[-•*]\s*", "", line).strip()
            if len(line) > 10 and "?" in line:
                questions.append(line)

        return {"questions": questions, "timings_ms": []}

    def _normalise_timings(self, timings_ms: list, questions: list[str]) -> list:
        result = []
        for i, question in enumerate(questions):
            if i < len(timings_ms):
                val = int(timings_ms[i])
                val = max(MIN_TIME_MS, min(MAX_TIME_MS, val))
            else:
                val = self.predict_time_ms(question)
            result.append(val)
        return result

    def predict_time_ms(self, question: str) -> int:
        q_lower = question.lower()
        for keywords, base_seconds in COMPLEXITY_RULES:
            if any(kw in q_lower for kw in keywords):
                return base_seconds * 1000
        return DEFAULT_TIME_MS

    def _fallback(self, qualification: str, job_description: str, question_count: int = DEFAULT_QUESTION_COUNT) -> dict:
        """Generic communication-focused questions when AI is unavailable."""
        questions = [
            "Tell me about a situation where you had to handle a disagreement with a colleague. What was the outcome?",
            "Tell me about yourself and how your background has prepared you for this role.",
            "Describe a time when you had to explain a complex idea to a non-technical audience. How did you approach it?",
            "How do you ensure clear communication when working with a remote or cross-functional team?",
            
            "Where do you see yourself professionally in the next three to five years, and how does this role fit that vision?",
        ]
        questions = questions[:question_count]
        timings_ms = [self.predict_time_ms(q) for q in questions]
        return {
            "questions":         questions,
            "timings_ms":        timings_ms,
            "generation_method": "fallback",
        }


# Backwards-compatibility alias
QuestionGenerator = questionGenerator

__all__ = ["questionGenerator", "QuestionGenerator"]
