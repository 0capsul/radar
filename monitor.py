#!/usr/bin/env python3
"""Monitors Reddit for lead-qualifying posts, scores them with an LLM, notifies via Telegram."""

import asyncio
import os
import sys
import warnings
from datetime import UTC, datetime

warnings.filterwarnings("ignore", message=".*unclosed.*", category=ResourceWarning)
warnings.filterwarnings("ignore", message=".*Unclosed.*")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.config import get_settings
from core.exceptions import GeminiServiceError, RedditAPIError, WebhookServiceError
from core.models import QualifiedPost, RedditPost
from services.gemini_service import GeminiService
from services.rate_limiter import delay_between_subreddits
from services.reddit_service import RedditService
from services.webhook_service import WebhookService

TITLE_PREVIEW_LENGTH = 60
MAX_PAIN_POINTS_SHOWN = 3
VERY_STRONG_THRESHOLD = 9
STRONG_THRESHOLD = 7
MODERATE_THRESHOLD = 5
TELEGRAM_MARKDOWN_SPECIAL_CHARS = "_*[]()~`>#+-=|{}.!"
PROCESSED_POSTS_FILE = "processed_posts.txt"


def _escape_telegram_markdown(text: str) -> str:
    for char in TELEGRAM_MARKDOWN_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


def _signal_strength(confidence: int, relevance: int) -> str:
    if confidence >= VERY_STRONG_THRESHOLD and relevance >= VERY_STRONG_THRESHOLD:
        return "Very strong"
    if confidence >= STRONG_THRESHOLD and relevance >= STRONG_THRESHOLD:
        return "Strong"
    if confidence >= MODERATE_THRESHOLD and relevance >= MODERATE_THRESHOLD:
        return "Worth a look"
    return "Weak"


def _format_notification(post: QualifiedPost) -> str:
    qualification = post.qualification
    confidence = qualification.confidence
    relevance = qualification.relevance_score
    esc = _escape_telegram_markdown

    signal = _signal_strength(confidence, relevance)

    pain_points = (
        " / ".join(qualification.pain_points[:MAX_PAIN_POINTS_SHOWN])
        if qualification.pain_points
        else "Not specified"
    )

    lead_reason = (
        qualification.reasons[0]
        if qualification.reasons
        else "General interpretation discussion"
    )

    return f"""\
{esc(signal)} lead \\({confidence}/{relevance}\\) in {esc(post.subreddit)}

[{esc(post.title)}]({post.permalink})

{esc(lead_reason)}
Struggling with: {esc(pain_points)}"""


async def _fetch_all_posts(
    reddit_service: RedditService, monitoring_config
) -> list[RedditPost]:
    all_posts: list[RedditPost] = []

    for idx, subreddit in enumerate(monitoring_config.subreddits):
        if idx > 0:
            await delay_between_subreddits()
        try:
            posts = await reddit_service.get_recent_posts(
                subreddit=subreddit,
                limit=monitoring_config.max_posts_per_subreddit,
                max_age_minutes=monitoring_config.post_age_limit_minutes,
            )
            all_posts.extend(posts)
            print(f"r/{subreddit}: {len(posts)} posts")
        except Exception as e:
            print(f"r/{subreddit}: error - {e}")

    print(f"Total: {len(all_posts)} posts")
    return all_posts


async def _qualify_post(
    gemini_service: GeminiService, post: RedditPost, monitoring_config
) -> QualifiedPost | None:
    qualification = await gemini_service.qualify_post(post)
    if not qualification:
        return None

    meets_confidence = (
        qualification.confidence >= monitoring_config.min_confidence_score
    )
    meets_relevance = (
        qualification.relevance_score >= monitoring_config.min_relevance_score
    )

    if meets_confidence and meets_relevance:
        print(
            f"  qualified ({qualification.confidence}/{qualification.relevance_score})"
        )
        return QualifiedPost(**post.model_dump(), qualification=qualification)

    print(f"  skipped ({qualification.confidence}/{qualification.relevance_score})")
    return None


async def _qualify_all_posts(
    gemini_service: GeminiService, posts: list[RedditPost], monitoring_config
) -> list[QualifiedPost]:
    qualified: list[QualifiedPost] = []

    for idx, post in enumerate(posts):
        try:
            print(f"[{idx + 1}/{len(posts)}] {post.title[:TITLE_PREVIEW_LENGTH]}")
            result = await _qualify_post(gemini_service, post, monitoring_config)
            if result:
                qualified.append(result)
        except GeminiServiceError as e:
            print(f"  gemini error: {e}")
        except Exception as e:
            print(f"  error: {e}")

    return qualified


async def process_posts() -> list[QualifiedPost]:
    """Fetch recent Reddit posts and return those that qualify as leads."""
    settings = get_settings()
    monitoring_config = settings.monitoring

    print(f"Started at {datetime.now(UTC):%H:%M:%S UTC}")
    print(f"Subreddits: {len(monitoring_config.subreddits)}")

    reddit_service = RedditService(
        settings.reddit, processed_posts_file=PROCESSED_POSTS_FILE
    )
    gemini_service = GeminiService(settings.gemini)

    try:
        all_posts = await _fetch_all_posts(reddit_service, monitoring_config)
        return await _qualify_all_posts(gemini_service, all_posts, monitoring_config)
    except RedditAPIError as e:
        print(f"Reddit error: {e}")
        return []


async def send_notifications(qualified_posts: list[QualifiedPost]) -> None:
    """Send Telegram notifications for each qualified post."""
    if not qualified_posts:
        print("No leads found")
        return

    settings = get_settings()
    webhook_service = WebhookService(settings.webhook)

    for post in qualified_posts:
        try:
            message = _format_notification(post)
            await webhook_service.send_notification(message)
            print(f"Notified: {post.title[:50]}")
        except WebhookServiceError as e:
            print(f"Notification failed: {e}")
        except Exception as e:
            print(f"Notification error: {e}")


async def main():
    """Run the full monitoring pipeline: fetch, qualify, notify."""
    try:
        qualified_posts = await process_posts()
        await send_notifications(qualified_posts)
        print(f"\nDone. {len(qualified_posts)} leads. {datetime.now(UTC):%H:%M:%S UTC}")
    except Exception as e:
        print(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
