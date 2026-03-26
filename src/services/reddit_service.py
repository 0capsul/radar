"""Reddit monitoring service using public JSON endpoints (no API keys needed)."""

import logging
from datetime import datetime
from pathlib import Path

import httpx

from core.config import RedditConfig
from core.exceptions import RedditAPIError
from core.models import RedditPost

logger = logging.getLogger(__name__)

BASE_URL = "https://www.reddit.com"
DEFAULT_USER_AGENT = "reddit-interpreter-monitor:v1.0 (by script)"
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_BODY_LENGTH = 500
MAX_SAVED_POST_IDS = 500


class RedditService:
    """Service for monitoring Reddit via public JSON endpoints."""

    def __init__(
        self, reddit_config: RedditConfig, processed_posts_file: str | None = None
    ):
        self._config = reddit_config
        self._processed_posts: set[str] = set()
        self._processed_posts_file = processed_posts_file or "processed_posts.txt"
        self._load_processed_posts()
        self._user_agent = reddit_config.user_agent or DEFAULT_USER_AGENT

    def _new_client(self) -> httpx.AsyncClient:
        """Create a fresh client per request to avoid session-based blocking."""
        return httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def _load_processed_posts(self) -> None:
        """Load previously processed post IDs from file."""
        processed_file = Path(self._processed_posts_file)
        if not processed_file.exists():
            return

        try:
            with open(processed_file) as f:
                self._processed_posts = {line.strip() for line in f if line.strip()}
            logger.info(f"Loaded {len(self._processed_posts)} processed post IDs")
        except Exception as e:
            logger.warning(f"Error loading processed posts: {e}")
            self._processed_posts = set()

    def _save_processed_posts(self) -> None:
        """Save processed post IDs to file, keeping only the most recent."""
        try:
            recent_posts = list(self._processed_posts)[-MAX_SAVED_POST_IDS:]
            processed_file = Path(self._processed_posts_file)
            with open(processed_file, "w") as f:
                for post_id in recent_posts:
                    f.write(f"{post_id}\n")

            self._processed_posts = set(recent_posts)
            logger.info(f"Saved {len(recent_posts)} processed post IDs")
        except Exception as e:
            logger.error(f"Error saving processed posts: {e}")

    def is_already_processed(self, post_id: str) -> bool:
        return post_id in self._processed_posts

    def _truncate_body(self, body: str) -> str:
        if len(body) > MAX_BODY_LENGTH:
            return body[:MAX_BODY_LENGTH] + "..."
        return body

    def _build_post(self, post_data: dict, matched_keywords: list[str]) -> RedditPost:
        """Convert Reddit JSON post data into a RedditPost."""
        raw_body = post_data.get("selftext", "") or ""
        return RedditPost(
            post_id=post_data["id"],
            subreddit=f"r/{post_data['subreddit']}",
            title=post_data["title"],
            body=self._truncate_body(raw_body),
            author=post_data.get("author", "[deleted]") or "[deleted]",
            permalink=f"https://reddit.com{post_data['permalink']}",
            created_utc=datetime.fromtimestamp(post_data["created_utc"]).isoformat(),
            score=post_data.get("score", 0),
            num_comments=post_data.get("num_comments", 0),
            matched_keywords=matched_keywords,
        )

    def _minutes_since(self, utc_timestamp: float) -> float:
        post_time = datetime.fromtimestamp(utc_timestamp)
        return (datetime.now() - post_time).total_seconds() / 60

    async def _fetch_subreddit_json(self, subreddit: str, limit: int) -> dict | None:
        """Fetch JSON listing from a subreddit. Returns None on expected HTTP errors."""
        url = f"{BASE_URL}/r/{subreddit}/new.json"
        async with self._new_client() as client:
            resp = await client.get(url, params={"limit": limit, "raw_json": 1})

        if resp.status_code == 403:
            logger.warning(f"r/{subreddit} returned 403, skipping")
            return None
        if resp.status_code == 404:
            logger.warning(f"r/{subreddit} not found, skipping")
            return None
        if resp.status_code == 429:
            logger.warning("Reddit rate limit hit, backing off")
            return None

        resp.raise_for_status()
        return resp.json()

    def _filter_new_posts(
        self, raw_posts: list[dict], max_age_minutes: int
    ) -> list[RedditPost]:
        """Filter raw posts by age and dedup, returning new RedditPost objects."""
        new_posts = []
        for item in raw_posts:
            post = item.get("data", {})
            created = post.get("created_utc", 0)

            if self._minutes_since(created) > max_age_minutes:
                continue
            if self.is_already_processed(post["id"]):
                continue

            new_posts.append(self._build_post(post, []))
            self._processed_posts.add(post["id"])

        return new_posts

    async def get_recent_posts(
        self,
        subreddit: str,
        limit: int = 25,
        max_age_minutes: int = 45,
    ) -> list[RedditPost]:
        """Get recent posts from a subreddit."""
        try:
            data = await self._fetch_subreddit_json(subreddit, limit)
            if data is None:
                return []

            raw_posts = data.get("data", {}).get("children", [])
            new_posts = self._filter_new_posts(raw_posts, max_age_minutes)

            if new_posts:
                self._save_processed_posts()

            return new_posts

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting posts from r/{subreddit}: {e}")
            raise RedditAPIError(
                f"Failed to get posts from r/{subreddit}", str(e)
            ) from e
        except RedditAPIError:
            raise
        except Exception as e:
            logger.error(f"Error getting posts from r/{subreddit}: {e}")
            raise RedditAPIError(
                f"Failed to get posts from r/{subreddit}", str(e)
            ) from e

    async def close(self):
        """No-op, clients are created and closed per request."""
