"""Webhook notification service."""

import logging

import httpx

from core.config import WebhookConfig
from core.exceptions import WebhookServiceError

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0


class WebhookService:
    """Service for sending webhook notifications."""

    def __init__(self, webhook_config: WebhookConfig):
        self._telegram_url = webhook_config.telegram_url

    def _is_bot_api_url(self) -> bool:
        return bool(self._telegram_url and "api.telegram.org/bot" in self._telegram_url)

    async def send_notification(self, message: str) -> bool:
        """Send a simple text notification to Telegram."""
        if not self._telegram_url:
            logger.warning("Telegram webhook URL not configured")
            return False

        try:
            payload = {
                "text": message,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            }

            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                if self._is_bot_api_url():
                    response = await client.post(
                        self._telegram_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                else:
                    response = await client.post(self._telegram_url, data=payload)
                response.raise_for_status()

            logger.info("Telegram notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e!s}")
            raise WebhookServiceError(f"Notification failed: {e!s}", str(e)) from e
