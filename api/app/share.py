"""Helper mode: expiring, signed read-only share links (HMAC, no DB needed)."""
import base64
import hashlib
import hmac
import time
from app.config import get_settings

def _secret() -> bytes:
    return get_settings().share_secret.strip().encode()


def make_token(case_id: str, ttl_hours: int = 24) -> str:
    exp = int(time.time()) + ttl_hours * 3600
    msg = f"{case_id}.{exp}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(msg + b"." + sig).decode().rstrip("=")


def read_token(token: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        case_id, exp, sig = raw.split(b".", 2)
        msg = case_id + b"." + exp
        if not hmac.compare_digest(sig, hmac.new(_secret(), msg, hashlib.sha256).digest()[:16]):
            return None
        if int(exp) < time.time():
            return None
        return case_id.decode()
    except Exception:  # noqa: BLE001
        return None
