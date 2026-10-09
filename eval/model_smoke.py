"""Real model availability probes. Run only after configuring the dedicated project/auth."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from google.genai import types
from app.config import get_settings
from app.llm import client


async def live_probe(model: str) -> dict:
    started = time.perf_counter()
    async with asyncio.timeout(45):
        async with client().aio.live.connect(model=model, config=types.LiveConnectConfig(
                response_modalities=["AUDIO"], output_audio_transcription=types.AudioTranscriptionConfig())) as session:
            await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(
                text="Say only: GoldenHour model check succeeded.")]), turn_complete=True)
            async for response in session.receive():
                content = response.server_content
                if content and content.model_turn:
                    audio = any(p.inline_data and p.inline_data.data for p in content.model_turn.parts or [])
                    if audio:
                        return {"ok": True, "first_audio_seconds": round(time.perf_counter() - started, 3)}
    raise RuntimeError("Live did not return audio")


def main() -> int:
    settings = get_settings()
    if (settings.use_vertex and not settings.gcp_project) or (not settings.use_vertex and not settings.gemini_api_key):
        print("Configure the dedicated GCP_PROJECT and ADC, or USE_VERTEX=false with GEMINI_API_KEY. No probes ran.")
        return 2
    results = []
    for role, model in (("main", settings.model_main), ("lite", settings.model_lite),
                        ("live", settings.model_live), ("live_fallback", settings.model_live_fallback)):
        started = time.perf_counter()
        try:
            if role.startswith("live"):
                result = asyncio.run(live_probe(model))
            else:
                response = client().models.generate_content(model=model,
                    contents="Reply with only GOLDENHOUR_OK", config=types.GenerateContentConfig(
                        temperature=0, max_output_tokens=256, http_options=types.HttpOptions(timeout=45000)))
                result = {"ok": "GOLDENHOUR_OK" in (response.text or ""),
                          "seconds": round(time.perf_counter() - started, 3),
                          "usage": response.usage_metadata.model_dump(mode="json") if response.usage_metadata else None}
            results.append({"role": role, "model": model, **result})
        except Exception as error:
            # Do not print credentials, raw HTTP URLs or access-token details.
            results.append({"role": role, "model": model, "ok": False,
                            "error_type": type(error).__name__, "status_code": getattr(error, "code", None)})
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "provider": "vertex" if settings.use_vertex else "gemini_api",
              "project": settings.gcp_project if settings.use_vertex else None,
              "region": settings.gcp_location, "results": results}
    out = Path(__file__).resolve().parent / "model_smoke.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    print(f"Saved actual results to {out}")
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
