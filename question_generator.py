"""
question_generator.py
─────────────────────
Generates tailored interview questions using OpenAI (ChatCompletion-compatible)
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
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util import ssl_ as urllib3_ssl
from urllib3.poolmanager import PoolManager
from groq import Groq

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
    Uses an OpenAI ChatCompletion-compatible API to generate a personalised set of
    interview questions for a candidate, each paired with a predicted
    answer duration so the frontend can set dynamic recording windows.
    """

    DEFAULT_QUESTION_COUNT = 5

    def __init__(self, api_key=None):
        # ── FIX: safely resolve API key — never call .strip() on None ─
        # Resolve GROQ API key and create a Groq client when available
        raw_key = (api_key or os.getenv("GROQ_API_KEY") or "").strip()
        self.api_key = raw_key
        self.groq_client = Groq(api_key=raw_key) if raw_key else None

        # Allow overriding model via env var (GROQ-compatible name)
        self.model   = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        # Resolve endpoint/base
        base = os.getenv("GROQ_API_BASE",  "https://api.groq.com").rstrip('/')
        self.endpoint = f"{base}/chat/completions"
        self.timeout = 30
        self.verify  = not bool(os.getenv("GROQ_INSECURE", os.getenv("OPENAI_INSECURE", "")).lower() in ("1", "true", "yes"))

        if self.groq_client:
            logger.info("🔐 Groq client initialized for question generation")
        else:
            logger.info("⚠️ No GROQ_API_KEY provided; falling back to local heuristics")

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
              "generation_method": "ai" | "fallback",
              "error": "..."   (only present on failure)
            }
        """
        if not self.api_key:
            logger.warning("No API key — using fallback questions")
            return self._fallback(qualification, job_description)

        try:
            logger.info(f"🚀 Starting question generation (count={question_count}, model={self.model})")
            prompt = self._build_prompt(qualification, job_description, candidate_name, question_count)
            raw    = self._call_api(prompt)
            logger.info(f"✅ API returned response (length: {len(raw)} chars)")

            parsed    = self._parse_response(raw)
            questions = parsed.get("questions", [])
            timings   = parsed.get("timings_ms", [])

            if not questions:
                logger.warning("AI returned no parseable questions — using fallback")
                return self._fallback(qualification, job_description)

            timings = self._normalise_timings(timings, len(questions))

            logger.info(f"✅ AI generated {len(questions)} questions with timings: {timings}")
            return {
                "questions":         questions,
                "timings_ms":        timings,
                "generation_method": "ai",
            }

        except Exception as exc:
            logger.error(f"❌ Question generation failed: {exc}", exc_info=True)
            fallback = self._fallback(qualification, job_description)
            fallback["error"] = str(exc)
            return fallback

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    def _build_prompt(self, qualification: str, job_description: str,
                      candidate_name: str, question_count: int) -> str:
        name_line = f"Candidate name: {candidate_name}\n" if candidate_name else ""
        return f"""You are an expert HR interviewer and communication coach.

Your task is to generate exactly {question_count} interview questions for a candidate based on the details below, and for each question predict how many SECONDS a well-prepared candidate would need to answer it fully.

{name_line}Candidate Qualification:
{qualification}

Job Description:
{job_description}

Requirements for the questions:
1. Each question must assess the candidate's COMMUNICATION SKILLS (clarity, structure, confidence, listening, articulation).
2. At least 2 questions should be role-specific, probing knowledge relevant to the job.
3. At least 1 question should be a behavioral / situational question (STAR method).
4. Questions must be open-ended (no yes/no answers).
5. Keep each question concise (1–2 sentences max).

Timing guidelines for predicted_seconds:
- Simple factual / introductory questions (e.g. "Tell me about yourself"): 60–90 s
- Behavioral / STAR questions (e.g. "Describe a challenging situation"): 90–120 s
- Technical / in-depth knowledge questions: 90–100 s
- Motivational / goal questions: 45–75 s
- Minimum allowed: 30 s. Maximum allowed: 150 s.

Respond ONLY with a valid JSON object in this exact format (no markdown fences, no extra text):
{{
  "questions": [
    "Question one?",
    "Question two?"
  ],
  "predicted_seconds": [75, 120]
}}

The arrays must be the same length ({question_count} items each).
"""

    def _call_api(self, prompt: str) -> str:
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model":       self.model,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens":  1000,
        }

        try:
            logger.info(f"OpenSSL: {getattr(ssl, 'OPENSSL_VERSION', 'unknown')}")
        except Exception:
            pass

        # First attempt: standard requests
        resp = None
        try:
            resp = requests.post(
                self.endpoint, headers=headers, json=payload,
                timeout=self.timeout, verify=self.verify
            )
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL/TLS handshake failed, trying TLSAdapter fallback", exc_info=True)
            try:
                class TLSAdapter(HTTPAdapter):
                    def init_poolmanager(self, connections, maxsize, block=False, **kw):
                        ctx = urllib3_ssl.create_urllib3_context()
                        try:
                            ctx.options |= getattr(ssl, 'OP_NO_TLSv1', 0) | getattr(ssl, 'OP_NO_TLSv1_1', 0)
                        except Exception:
                            pass
                        kw['ssl_context'] = ctx
                        self.poolmanager = PoolManager(
                            num_pools=connections, maxsize=maxsize, block=block, **kw
                        )

                session = requests.Session()
                session.trust_env = False
                session.mount('https://', TLSAdapter())
                resp = session.post(
                    self.endpoint, headers=headers, json=payload,
                    timeout=self.timeout, verify=self.verify
                )
            except requests.exceptions.SSLError as e2:
                raise RuntimeError(
                    "SSL handshake failed. Try: 1) upgrade Python/OpenSSL; "
                    "2) disable HTTPS scanning in AV/firewall; "
                    "3) set GROQ_INSECURE=1 for local testing only."
                ) from e2

        logger.info(f"API response status: {resp.status_code}")

        if resp.status_code == 401:
            raise RuntimeError(
                f"401 Unauthorized — GROQ_API_KEY is invalid or expired. "
                f"Key preview: {self.api_key[:12]}... "
                f"Visit https://www.groq.ai/docs/getting-started to check your key."
            )

        if resp.status_code == 429:
            text = resp.text or ""
            raise RuntimeError(
                f"429 Rate limit / quota exceeded: {text[:300]}. "
                "Check billing at your Groq account dashboard or https://www.groq.ai/docs"
            )

        # Model-not-found: retry with safe fallback
        if resp.status_code == 400:
            text = resp.text or ""
            if "model" in text.lower() and resp.status_code == 400:
                fallback_model = os.getenv("GROQ_MODEL_FALLBACK","llama-3.1-70b-versatile")
                if payload.get("model") != fallback_model:
                    logger.warning(f"Model '{payload['model']}' not found; retrying with '{fallback_model}'")
                    payload["model"] = fallback_model
                    resp = requests.post(
                        self.endpoint, headers=headers, json=payload,
                        timeout=self.timeout, verify=self.verify
                    )

        if resp.status_code != 200:
            raise RuntimeError(f"API returned {resp.status_code}: {resp.text[:300]}")

        data    = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        logger.info(f"Successfully retrieved {len(content)} chars from API")
        return content

    def _parse_response(self, raw: str) -> dict:
        """
        Parse the AI response. Handles:
        - Clean JSON object  {"questions": [...], "predicted_seconds": [...]}
        - JSON wrapped in ```json ... ```
        - Fallback: extract question-looking lines + use heuristic timing
        """
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                questions  = parsed.get("questions", [])
                seconds    = parsed.get("predicted_seconds", [])
                timings_ms = [int(s) * 1000 for s in seconds if isinstance(s, (int, float))]
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

    def _normalise_timings(self, timings_ms: list, count: int) -> list:
        result = []
        for i in range(count):
            if i < len(timings_ms):
                val = int(timings_ms[i])
                val = max(MIN_TIME_MS, min(MAX_TIME_MS, val))
            else:
                val = DEFAULT_TIME_MS
            result.append(val)
        return result

    def predict_time_ms(self, question: str) -> int:
        q_lower = question.lower()
        for keywords, base_seconds in COMPLEXITY_RULES:
            if any(kw in q_lower for kw in keywords):
                return base_seconds * 1000
        return DEFAULT_TIME_MS

    def _fallback(self, qualification: str, job_description: str) -> dict:
        """Generic communication-focused questions when AI is unavailable."""
        questions = [
            "Tell me about a situation where you had to handle a disagreement with a colleague. What was the outcome?",
            "Tell me about yourself and how your background has prepared you for this role.",
            "Describe a time when you had to explain a complex idea to a non-technical audience. How did you approach it?",
            "How do you ensure clear communication when working with a remote or cross-functional team?",
            
            "Where do you see yourself professionally in the next three to five years, and how does this role fit that vision?",
        ]
        timings_ms = [self.predict_time_ms(q) for q in questions]
        return {
            "questions":         questions,
            "timings_ms":        timings_ms,
            "generation_method": "fallback",
        }


# Backwards-compatibility alias
QuestionGenerator = questionGenerator

__all__ = ["questionGenerator", "QuestionGenerator"]