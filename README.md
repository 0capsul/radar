# Reddit Lead Monitor

Finds business leads on Reddit for Interpreter — a real-time transcription and translation tool for over-the-phone interpreters.

The system monitors relevant subreddits, uses AI to qualify posts, and sends Telegram notifications when it finds professional interpreters who could benefit from the product.

## How it works

The monitor checks Reddit posts from interpretation communities hourly. When someone posts about needing transcription tools, struggling with note-taking during calls, or dealing with cognitive overload while interpreting, AI analyzes the post and scores its relevance.

High-scoring posts get sent to Telegram with analysis and pain point identification.

## Setup

Create these environment variables:

```bash
# Reddit API
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_secret
REDDIT_USERNAME=your_username
REDDIT_PASSWORD=your_password

# AI qualification
GEMINI_API_KEY=your_gemini_key

# Notifications
TELEGRAM_WEBHOOK_URL=your_webhook_url
```

## Installation

Install dependencies with uv:
```bash
uv sync
```

Run locally:
```bash
python monitor.py
```

Runs automatically on GitHub Actions every hour in production.

## Architecture

```
src/
|-- core/           # Configuration and models
|-- services/       # Reddit, AI, and notification services

monitor.py          # Main entry point
```

## What it monitors

Subreddits related to interpretation, medical interpreting, legal interpreting, remote work, and language services. Looks for posts about:

- Note-taking struggles during live interpretation
- Cognitive overload and interpreter burnout
- Speech-to-text and transcription needs
- Real-time captioning and translation tools
- OPI, VRI, and remote interpreting challenges

## AI qualification

Posts get scored 1-10 on confidence and relevance using Google Gemini. The AI understands Interpreter's product (real-time transcription, quick lookup, term mappings, domain modes) and scores based on how well the poster's pain points match what Interpreter solves.

Only posts scoring 5+ on both confidence and relevance generate notifications.

## Performance

Processes 20-50 posts per run in 2-3 minutes. Rate limited to respect API constraints. Tracks processed posts to avoid duplicates.
