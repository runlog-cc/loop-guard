"""Real-time alerting dispatchers for Slack, Telegram, and generic Webhooks."""

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("loopguard.alerts")


class AlertDispatcher:
    """Dispatches real-time alerts when a circuit breaker trips."""

    def __init__(
        self,
        slack_webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        generic_webhook_url: Optional[str] = None,
        async_dispatch: bool = True,
    ):
        self.slack_webhook_url = slack_webhook_url
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.generic_webhook_url = generic_webhook_url
        self.async_dispatch = async_dispatch

    def notify_trip(self, session_data: Dict[str, Any], trip_details: Dict[str, Any]):
        """Trigger alerts across all configured channels."""
        if self.async_dispatch:
            thread = threading.Thread(
                target=self._send_all,
                args=(session_data, trip_details),
                daemon=True
            )
            thread.start()
        else:
            self._send_all(session_data, trip_details)

    def _send_all(self, session_data: Dict[str, Any], trip_details: Dict[str, Any]):
        if self.slack_webhook_url:
            self.send_slack(session_data, trip_details)
        if self.telegram_bot_token and self.telegram_chat_id:
            self.send_telegram(session_data, trip_details)
        if self.generic_webhook_url:
            self.send_generic(session_data, trip_details)

    def send_slack(self, session_data: Dict[str, Any], trip_details: Dict[str, Any]):
        if not self.slack_webhook_url:
            return

        session_id = session_data.get("session_id", "unknown")
        reason = trip_details.get("reason") or session_data.get("trip_reason", "UNKNOWN")
        cost = session_data.get("budget", {}).get("total_cost_usd", 0.0)
        tool_name = trip_details.get("tool_name", "N/A")
        depth = session_data.get("current_depth", 0)

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 Loop-Guard Alert: Circuit Tripped!",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Reason:* `{reason}`\n"
                            f"*Session ID:* `{session_id}`\n"
                            f"*Failing Tool:* `{tool_name}`\n"
                            f"*Depth:* `{depth}` steps\n"
                            f"*Cost Incurred:* `${cost:.4f}`\n"
                            f"*Status:* Execution halted gracefully to prevent runaway bill."
                        ),
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "🛡️ *Protected by RunLog Loop-Guard (runlog.cc)*",
                        }
                    ],
                },
            ]
        }

        self._http_post_json(self.slack_webhook_url, payload)

    def send_telegram(self, session_data: Dict[str, Any], trip_details: Dict[str, Any]):
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return

        session_id = session_data.get("session_id", "unknown")
        reason = trip_details.get("reason") or session_data.get("trip_reason", "UNKNOWN")
        cost = session_data.get("budget", {}).get("total_cost_usd", 0.0)
        tool_name = trip_details.get("tool_name", "N/A")

        text = (
            f"🚨 <b>Loop-Guard: Circuit Breaker Tripped!</b>\n\n"
            f"• <b>Reason:</b> <code>{reason}</code>\n"
            f"• <b>Session:</b> <code>{session_id}</code>\n"
            f"• <b>Tool:</b> <code>{tool_name}</code>\n"
            f"• <b>Cost:</b> <code>${cost:.4f}</code>\n\n"
            f"<i>Execution halted safely to save tokens.</i>"
        )

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        self._http_post_json(url, payload)

    def send_generic(self, session_data: Dict[str, Any], trip_details: Dict[str, Any]):
        if not self.generic_webhook_url:
            return

        payload = {
            "event": "circuit_breaker.tripped",
            "session": session_data,
            "trip_details": trip_details,
        }
        self._http_post_json(self.generic_webhook_url, payload)

    def _http_post_json(self, url: str, data: Dict[str, Any]):
        try:
            req_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json", "User-Agent": "RunLog-LoopGuard/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception as e:
            logger.warning(f"Failed to deliver alert to {url}: {e}")
