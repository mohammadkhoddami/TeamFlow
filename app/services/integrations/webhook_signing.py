"""Webhook signing: HMAC-SHA256 over `{timestamp}.{body}` with the org's secret.

Receivers verify by recomputing the digest; the timestamp guards replay
windows (recommend rejecting timestamps older than 5 minutes).
"""

import hashlib
import hmac


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp}.".encode())
    mac.update(body)
    return "v1=" + mac.hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
