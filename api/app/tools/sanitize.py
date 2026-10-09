"""Portal-safe text: strip characters a portal rejects and enforce a minimum length."""
import re


def sanitize(text: str, forbidden: str) -> str:
    if not text:
        return ""
    out = text
    for ch in forbidden:
        out = out.replace(ch, "")
    # replace common symbols with words instead of silently losing meaning
    out = out.replace("&", " and ").replace("%", " percent")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def pad_to_min(text: str, min_chars: int, filler: str) -> str:
    if len(text) >= min_chars:
        return text
    return (text + " " + filler).strip()


def portal_ok(text: str, forbidden: str, min_chars: int) -> bool:
    return len(text) >= min_chars and not any(ch in text for ch in forbidden)
