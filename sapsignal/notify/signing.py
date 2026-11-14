"""HMAC-signed approval links. The Cloudflare Worker (approval-worker/) verifies the same signature,
so a link only works for the action and edition it was issued for, and only until it expires."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

ACTIONS = ("approve", "reject", "regenerate", "run", "notes")


def _secret() -> bytes:
    s = os.environ.get("APPROVAL_SECRET", "")
    if len(s) < 32:
        raise RuntimeError("APPROVAL_SECRET must be set (32+ random characters) to build approval links")
    return s.encode()


def sign(action: str, edition_date: str, exp: int, secret: bytes | None = None) -> str:
    msg = f"{action}:{edition_date}:{exp}".encode()
    return hmac.new(secret or _secret(), msg, hashlib.sha256).hexdigest()


def verify(action: str, edition_date: str, exp: int, sig: str, secret: bytes | None = None,
           now: float | None = None) -> bool:
    if action not in ACTIONS or (now or time.time()) > exp:
        return False
    return hmac.compare_digest(sign(action, edition_date, exp, secret), sig)


def decision_link(worker_url: str, action: str, edition_date: str, ttl_hours: int = 36,
                  secret: bytes | None = None) -> str:
    exp = int(time.time()) + ttl_hours * 3600
    q = urlencode({"action": action, "date": edition_date, "exp": exp,
                   "sig": sign(action, edition_date, exp, secret)})
    return f"{worker_url.rstrip('/')}/decide?{q}"
