from pydantic import BaseModel, Field, field_validator


class RedditPost(BaseModel):
    post_id: str
    subreddit: str
    title: str
    body: str = ""
    author: str
    permalink: str
    created_utc: str
    score: int
    num_comments: int
    matched_keywords: list[str] = Field(default_factory=list)

    @field_validator("subreddit")
    @classmethod
    def ensure_subreddit_prefix(cls, raw_subreddit: str) -> str:
        if not raw_subreddit.startswith("r/"):
            return f"r/{raw_subreddit}"
        return raw_subreddit

    @field_validator("score", "num_comments")
    @classmethod
    def clamp_to_zero_floor(cls, value: int) -> int:
        return max(0, value)

    def __repr__(self) -> str:
        title_preview = self.title[:80] + "..." if len(self.title) > 80 else self.title
        return (
            f"RedditPost(post_id={self.post_id!r}, subreddit={self.subreddit!r}, "
            f"title={title_preview!r}, author={self.author!r})"
        )


class PostQualification(BaseModel):
    needs_interpreter: bool
    confidence: int = Field(ge=1, le=10)
    reasons: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    relevance_score: int = Field(ge=1, le=10)

    def __repr__(self) -> str:
        return (
            f"PostQualification(needs_interpreter={self.needs_interpreter}, "
            f"confidence={self.confidence}, relevance_score={self.relevance_score})"
        )


class QualifiedPost(RedditPost):
    qualification: PostQualification

    def __repr__(self) -> str:
        return (
            f"QualifiedPost(post_id={self.post_id!r}, subreddit={self.subreddit!r}, "
            f"qualification={self.qualification!r})"
        )
