"""Country rules packs: helplines, portal rules, ID formats, scripts. New country = new YAML."""
from functools import lru_cache
from pathlib import Path

import yaml

PACK_DIR = Path(__file__).resolve().parent.parent / "packs"


@lru_cache
def load_pack(code: str) -> dict:
    path = PACK_DIR / f"{code.upper()}.yaml"
    if not path.exists():
        raise KeyError(f"No country pack for {code}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def available_packs() -> list[dict]:
    out = []
    for p in sorted(PACK_DIR.glob("*.yaml")):
        pack = load_pack(p.stem)
        out.append({
            "code": pack["code"],
            "name": pack["name"],
            "currency": pack["currency"],
            "languages": pack["languages"],
            "helplines": pack["helplines"],
        })
    return out
