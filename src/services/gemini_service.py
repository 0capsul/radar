"""Gemini AI service for post qualification with multi-key retry mechanism."""

import json
import random
from http import HTTPStatus

import httpx

from core.config import GeminiConfig
from core.exceptions import GeminiAPIError
from core.models import PostQualification, RedditPost

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_interpreter": {
            "type": "boolean",
            "description": "True if the author needs Interpreter's real-time transcription and translation tool, False otherwise",
        },
        "confidence": {
            "type": "integer",
            "description": "Confidence level from 1-10 (10 being most confident)",
            "minimum": 1,
            "maximum": 10,
        },
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of specific reasons why this post does/doesn't need Interpreter",
        },
        "pain_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific challenges mentioned in the post",
        },
        "relevance_score": {
            "type": "integer",
            "description": "Relevance score from 1-10 for Interpreter",
            "minimum": 1,
            "maximum": 10,
        },
    },
    "required": [
        "needs_interpreter",
        "confidence",
        "reasons",
        "pain_points",
        "relevance_score",
    ],
}


class GeminiService:
    """Service for AI qualification using Google Gemini with infinite retry."""

    def __init__(self, gemini_config: GeminiConfig):
        self.gemini_config = gemini_config

        if not self.gemini_config.api_keys:
            raise GeminiAPIError(
                "No Gemini API keys configured",
                "Please set GEMINI_API_KEY1, GEMINI_API_KEY2, etc. in environment",
            )

        print(f"Loaded {len(self.gemini_config.api_keys)} Gemini API keys")

        self.system_prompt = """
You are an expert at identifying professional interpreters who have immediate pain points that Interpreter can solve.

WHAT INTERPRETER IS:
Interpreter is a real-time transcription and translation tool for over-the-phone interpreters. It listens to calls through a web app or Chrome extension, transcribes speech as it happens (sub-500ms latency), and translates on tap or in real time. Available at app.useinterpreter.com and as a Chrome extension.

INTERPRETER SOLVES:
- Cognitive overload during live interpretation sessions — every word appears on screen so interpreters can focus on interpreting instead of scribbling notes
- Missed terms mid-call — Quick Lookup (Ctrl+K) for instant dictionary/translation without interrupting the call
- Difficulty with specialized terminology — 10 domain-specific modes (Medical, Legal, Banking, Insurance, Social Services, Government, Education, Customer Service, Technical, General)
- Memory/accuracy challenges in long or complex sessions — running transcript in both languages
- Fatigue from back-to-back interpretation work — eliminates the split attention of note-taking
- Unfamiliar vocabulary — Term Mappings (custom glossary, e.g. "MRI" always becomes "resonancia magnetica")

KEY FEATURES:
- Real-time transcription with sub-500ms latency
- Two-way translation (both speakers translated simultaneously)
- 60+ languages with automatic dialect detection
- Speaker identification, code-switching support
- Chrome extension with Focus Shield (hides from agency monitoring software)
- HIPAA compliant, SOC 2 Type II, GDPR compliant
- Pay-as-you-go: $0.20-0.35/hour, no subscription

IDEAL USER PROFILE:
- OPI (over-the-phone) interpreters at language service agencies (LanguageLine, TransPerfect, Teleperformance, CyraCom, Boostlingo, etc.)
- Interpreters working via phone, Zoom, Teams, WebEx, or any browser-based phone system
- Handling sessions 1+ hours or high-complexity topics
- Currently struggling with note-taking, cognitive load, or missed terms

SCORING CRITERIA:

Confidence 9-10 + Relevance 9-10:
- Professional interpreter explicitly struggling with note-taking, memory, fatigue, or missed terms during live calls
- Asks for tools to help with live interpretation workflow
- Describes specific pain: "can't keep up with notes", "forget details", "exhausted after long sessions", "missed a term", "had to ask them to repeat"

Confidence 7-8 + Relevance 7-8:
- Professional interpreter discussing workflow challenges (not explicitly asking for tools)
- Interpreter mentioning session difficulty
- Interpreter discussing cognitive load, burnout, or accuracy concerns
- OPI interpreter describing agency work challenges

Confidence 4-6 + Relevance 4-6:
- Interpretation students or trainees
- Occasional/part-time interpreters
- General interpretation career discussions
- ASL interpreters (Interpreter is audio-based, less directly applicable)

Confidence 1-3 + Relevance 1-3:
- Language learners or casual multilingual users
- Document translation (not live interpretation)
- People seeking interpretation services (not interpreters themselves)
- Academic language research
- AI/machine translation discussions (not about human interpreters)

OUTPUT STYLE — your output will be read by a human on Telegram. It must read like a person wrote it, not an AI.

"reasons" field — 1-2 short sentences max. Say what the person does and what they're struggling with.
  GOOD: "OPI interpreter at LanguageLine, been doing it 4 years. Struggling on long calls because she keeps missing terms."
  GOOD: "Interpreter asking how other people handle note-taking during long sessions."
  BAD: "This individual demonstrates significant alignment with the target user profile, highlighting key pain points." (corporate filler — never do this)
  BAD: "The post underscores the challenges faced by professional interpreters in high-stakes environments." (inflated significance — never do this)
  BAD: "Additionally, the author's experience showcases the intricate interplay between cognitive load and interpretation accuracy." (AI vocabulary soup — never do this)

"pain_points" field — use their actual words where possible. Each item under 10 words. Plain language only.
  GOOD: ["missing terms on long calls", "can't keep up with notes", "exhausted after back-to-back sessions"]
  BAD: ["Difficulty retaining specialized pharmaceutical terminology during extended sessions"] (synonym cycling + filler)
  BAD: ["Cognitive overload stemming from the intricate demands of simultaneous interpretation"] (nobody talks like this)

BANNED PATTERNS — if you catch yourself writing any of these, rewrite:
- Words: additionally, furthermore, moreover, crucial, pivotal, significant, landscape, testament, showcases, underscores, highlights, encompasses, fostering, delve, intricate, interplay, tapestry, vibrant, rich (figurative), profound, enduring, valuable, enhance, garner, align with, commitment to
- Constructions: "serves as a...", "stands as a...", "it's not just X, it's Y", "from X to Y" (false ranges), "X, Y, and Z" forced triples, "ensuring that...", "reflecting the...", "highlighting the..."
- Filler: "it is important to note", "in order to", "due to the fact that", "demonstrates", "indicates", "suggests potential"
- Style: no em dashes, no bold text formatting, no lists with bold headers, no generic positive conclusions

Write like you're telling a coworker about a Reddit post you just read. Short. Specific. No fluff.

IMPORTANT:
- needs_interpreter = true ONLY if confidence >= 7 AND relevance >= 7
- Be conservative: when in doubt, score lower
- Focus on immediate pain points, not theoretical interest
- The best leads are working interpreters with active pain, not people curious about the field
"""

    def __repr__(self) -> str:
        key_count = len(self.gemini_config.api_keys)
        model = self.gemini_config.model_name
        return f"GeminiService(keys={key_count}, model={model!r})"

    def _get_random_api_key(self) -> str:
        """Get a random API key from the pool."""
        return random.choice(self.gemini_config.api_keys)

    def _format_post_text(self, post: RedditPost) -> str:
        """Format a Reddit post into the text block sent to Gemini."""
        return (
            f"SUBREDDIT: {post.subreddit}\n"
            f"TITLE: {post.title}\n"
            f"CONTENT: {post.body or 'No content'}"
        )

    def _build_payload(self, post: RedditPost) -> dict:
        """Build the Gemini API request payload for a post."""
        post_text = self._format_post_text(post)
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"{self.system_prompt}\n\nAnalyze this Reddit post:\n\n{post_text}"
                        }
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }

    def _build_url(self, api_key: str) -> str:
        """Build the Gemini API endpoint URL for a given key."""
        return f"{self.gemini_config.base_url}/{self.gemini_config.model_name}:generateContent?key={api_key}"

    async def _send_request(self, payload: dict, api_key: str) -> httpx.Response:
        """Send a single request to the Gemini API."""
        async with httpx.AsyncClient(timeout=self.gemini_config.timeout) as client:
            return await client.post(
                self._build_url(api_key),
                headers={"Content-Type": "application/json"},
                json=payload,
            )

    def _parse_qualification(
        self, response: httpx.Response
    ) -> PostQualification | None:
        """Extract a PostQualification from a Gemini response, or None if no candidates."""
        result = response.json()
        candidates = result.get("candidates", [])

        if not candidates:
            return None

        raw_text = candidates[0]["content"]["parts"][0]["text"]
        qualification_data = json.loads(raw_text)
        return PostQualification(**qualification_data)

    async def qualify_post(self, post: RedditPost) -> PostQualification | None:
        """
        Qualify a Reddit post using Gemini's structured output generation.
        Retries infinitely with random API keys until successful.
        """
        payload = self._build_payload(post)

        attempt = 0
        while True:
            attempt += 1
            api_key = self._get_random_api_key()

            try:
                response = await self._send_request(payload, api_key)

                if response.status_code != HTTPStatus.OK:
                    print(
                        f"Attempt {attempt}: API error {response.status_code}, retrying with different key..."
                    )
                    continue

                qualification = self._parse_qualification(response)
                if qualification is None:
                    print(
                        f"Attempt {attempt}: No candidates in response, retrying with different key..."
                    )
                    continue

                if attempt > 1:
                    print(f"Success on attempt {attempt}")
                return qualification

            except (json.JSONDecodeError, httpx.TimeoutException) as e:
                error_label = (
                    "Timeout"
                    if isinstance(e, httpx.TimeoutException)
                    else "JSON decode error"
                )
                print(
                    f"Attempt {attempt}: {error_label}, retrying with different key..."
                )
                continue
            except Exception as e:
                print(
                    f"Attempt {attempt}: Error ({e!s}), retrying with different key..."
                )
                continue
