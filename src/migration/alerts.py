"""Failure alerts to a chat channel (Slack or Teams incoming webhook).

The webhook URL comes from the environment. Without it, alerts are only logged. An alert
that cannot be delivered never hides the original failure.
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("migration.alerts")


def send(webhook_url: str | None, title: str, lines: list[str]) -> bool:
    message = f"*{title}*\n" + "\n".join(f"• {line}" for line in lines)
    log.warning("ALERT %s | %s", title, " | ".join(lines))
    if not webhook_url:
        return False
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except OSError as exc:
        log.error("alert could not be delivered: %s", exc)
        return False
