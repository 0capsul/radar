# radar

Monitors Reddit for lead-qualifying posts, scores them with an LLM, and pushes notifications to Telegram.

## How it works

A scheduled GitHub Actions job fetches recent posts from a list of subreddits using Reddit's public JSON API. Each post goes through an LLM (Gemini) that scores it on two axes: confidence and relevance (both 1-10). Posts that clear the threshold get formatted and sent to a Telegram channel.

No Reddit API keys needed. The public `.json` endpoints work with just a User-Agent header.

## Setup

```bash
uv sync
```

Two environment variables are required:

```
GEMINI_API_KEY=your_key
TELEGRAM_WEBHOOK_URL=https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>
```

Supports multiple Gemini keys as `GEMINI_API_KEY1`, `GEMINI_API_KEY2`, etc. The service picks a random key per request and retries with a different one on failure.

## Running

```bash
uv run python monitor.py
```

In production, a GitHub Actions cron triggers this hourly.

## Project structure

```
monitor.py              Entry point. Fetches, qualifies, notifies.
src/
  core/
    config.py            Pydantic settings, loaded from env vars
    models.py            RedditPost, PostQualification, QualifiedPost
    exceptions.py        Custom exception hierarchy
  services/
    reddit_service.py    Fetches posts via Reddit public JSON
    gemini_service.py    LLM qualification with multi-key retry
    webhook_service.py   Sends formatted messages to Telegram
    rate_limiter.py      Per-service call frequency tracking
```

## LLM qualification

The Gemini service wraps each post in a system prompt that defines scoring criteria. The response is structured JSON with confidence, relevance, reasons, and pain points.

Retry mechanism: picks a random API key from the pool, fires the request, retries with a different key on 429/403/timeout. No backoff, no max retries. Works because the key pool is large enough that something is always available.

## Rate limiting

Reddit: 95 requests/minute with configurable batch sizes and delays between batches.
Gemini: 14 requests/minute per key, distributed across the key pool.
Both tracked with a sliding 60-second window.

## Notifications

Qualified posts are formatted as Telegram MarkdownV2 messages with the lead signal strength, a link to the post, the LLM's one-line reason, and extracted pain points. All special characters are escaped before sending.

## Dev tools

```bash
uv run ruff check --fix .    # lint and auto-fix
uv run ruff format .         # format
uv run ty check              # type check
```

Ruff rules: E, F, I, UP, B, SIM, RUF. Type checking targets Python 3.12.
