"""Simple delay helper for pacing requests."""

import asyncio

SUBREDDIT_DELAY_SECONDS = 3


async def delay_between_subreddits() -> None:
    await asyncio.sleep(SUBREDDIT_DELAY_SECONDS)
