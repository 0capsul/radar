#!/usr/bin/env python3
"""
Interpreter Reddit Monitor - GitHub Actions Script

Monitors Reddit for professional interpreters who could benefit from
real-time transcription and translation during live calls.
"""

import asyncio
import os
import sys
import warnings
from datetime import UTC, datetime

# Suppress unclosed client session warnings from asyncpraw
warnings.filterwarnings("ignore", message=".*unclosed.*", category=ResourceWarning)
warnings.filterwarnings("ignore", message=".*Unclosed.*")

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.config import get_settings
from core.exceptions import GeminiServiceError, RedditAPIError, WebhookServiceError
from core.models import QualifiedPost, RedditPost
from services.gemini_service import GeminiService
from services.rate_limiter import rate_limiter
from services.reddit_service import RedditService
from services.webhook_service import WebhookService

SUBREDDIT_DELAY_SECONDS = 5
TITLE_PREVIEW_LENGTH = 60
TITLE_SHORT_PREVIEW_LENGTH = 40
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


async def _fetch_posts_from_subreddit(
    reddit_service: RedditService, subreddit: str, monitoring_config
) -> list[RedditPost]:
    try:
        posts = await reddit_service.get_recent_posts(
            subreddit=subreddit,
            limit=monitoring_config.max_posts_per_subreddit,
            max_age_minutes=monitoring_config.post_age_limit_minutes,
        )
        print(f"Found {len(posts)} relevant posts in r/{subreddit}")
        return posts
    except Exception as e:
        print(f"Error processing r/{subreddit}: {e}")
        return []


async def _fetch_all_posts(
    reddit_service: RedditService, monitoring_config, rate_limits
) -> list[RedditPost]:
    batches = [
        monitoring_config.subreddits[i : i + rate_limits.reddit_batch_size]
        for i in range(
            0, len(monitoring_config.subreddits), rate_limits.reddit_batch_size
        )
    ]

    all_posts: list[RedditPost] = []

    for batch_idx, subreddit_batch in enumerate(batches):
        if batch_idx > 0:
            await rate_limiter.wait_between_batches(
                rate_limits.reddit_delay_between_batches
            )

        print(
            f"Processing batch {batch_idx + 1}/{len(batches)}: {len(subreddit_batch)} subreddits"
        )

        for sub_idx, subreddit in enumerate(subreddit_batch):
            if sub_idx > 0:
                await asyncio.sleep(SUBREDDIT_DELAY_SECONDS)
            posts = await _fetch_posts_from_subreddit(
                reddit_service, subreddit, monitoring_config
            )
            all_posts.extend(posts)

    print(f"Total posts found: {len(all_posts)}")
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
            f"Post qualified (confidence: {qualification.confidence}, relevance: {qualification.relevance_score})"
        )
        return QualifiedPost(**post.model_dump(), qualification=qualification)

    print(
        f"Post not qualified (confidence: {qualification.confidence}, relevance: {qualification.relevance_score})"
    )
    return None


async def _qualify_all_posts(
    gemini_service: GeminiService, posts: list[RedditPost], monitoring_config
) -> list[QualifiedPost]:
    qualified: list[QualifiedPost] = []

    for idx, post in enumerate(posts):
        try:
            print(
                f"Analyzing ({idx + 1}/{len(posts)}): {post.title[:TITLE_PREVIEW_LENGTH]}..."
            )
            result = await _qualify_post(gemini_service, post, monitoring_config)
            if result:
                qualified.append(result)
        except GeminiServiceError as e:
            print(f"AI processing error for post {post.post_id}: {e}")
        except Exception as e:
            print(f"Unexpected error processing post {post.post_id}: {e}")

    print(f"Qualified {len(qualified)} posts for Interpreter")
    return qualified


async def process_posts() -> list[QualifiedPost]:
    """Fetch recent Reddit posts and return those that qualify as leads."""
    settings = get_settings()
    monitoring_config = settings.monitoring

    print(f"Starting Interpreter monitoring at {datetime.now(UTC)}")
    print(f"Monitoring {len(monitoring_config.subreddits)} subreddits")

    reddit_service = RedditService(
        settings.reddit, processed_posts_file=PROCESSED_POSTS_FILE
    )
    gemini_service = GeminiService(settings.gemini)

    try:
        all_posts = await _fetch_all_posts(
            reddit_service, monitoring_config, settings.rate_limits
        )
        return await _qualify_all_posts(gemini_service, all_posts, monitoring_config)
    except RedditAPIError as e:
        print(f"Reddit monitoring error: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []


async def send_notifications(qualified_posts: list[QualifiedPost]) -> None:
    """Send Telegram notifications for each qualified post."""
    if not qualified_posts:
        print("No qualified posts to notify about")
        return

    settings = get_settings()
    webhook_service = WebhookService(settings.webhook)

    for post in qualified_posts:
        try:
            message = _format_notification(post)
            await webhook_service.send_notification(message)
            print(
                f"Sent notification for: {post.title[:TITLE_SHORT_PREVIEW_LENGTH]}..."
            )
        except WebhookServiceError as e:
            print(f"Failed to send notification: {e}")
        except Exception as e:
            print(f"Unexpected notification error: {e}")


def _print_summary(qualified_posts: list[QualifiedPost]) -> None:
    reddit_usage = rate_limiter.get_current_usage("reddit")
    print("\nInterpreter Monitoring Summary:")
    print(f"{len(qualified_posts)} qualified opportunities found")
    print(f"Reddit API: {reddit_usage['calls_last_minute']}/95 requests used")
    print(f"Completed at {datetime.now(UTC)}")
    print("Next check in 1 hour")


async def main():
    """Run the full monitoring pipeline: fetch, qualify, notify."""
    print("Interpreter Reddit Monitor Starting...")

    try:
        qualified_posts = await process_posts()
        await send_notifications(qualified_posts)
        _print_summary(qualified_posts)
    except RedditAPIError as e:
        print(f"\nReddit API Error: {e}")
        print("The monitoring run failed due to Reddit authentication issues.")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error in Interpreter monitor: {e}")
        sys.exit(1)
    finally:
        try:
            import gc

            gc.collect()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
