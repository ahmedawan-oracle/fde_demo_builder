#!/usr/bin/env python3
"""Deterministic checks for the optional OCI Speech adapter."""

from __future__ import annotations

import base64
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "demo-video-builder" / "scripts"))

from tts_providers import bump_speed, normalize_voice, parse_oci_response  # noqa: E402


def main() -> None:
    edge = normalize_voice(("en-US-AvaNeural", "+3%"))
    assert edge == {"provider": "edge", "voice": "en-US-AvaNeural", "speed": "+3%"}
    oci = normalize_voice({"provider": "oci_speech", "voice": "Annabelle", "tempo": 0.96, "profile": "DEFAULT"})
    assert oci["provider"] == "oci_speech" and oci["profile"] == "DEFAULT" and oci["speed"] == 0.96
    assert bump_speed("edge", "+3%", 7) == "+10%"
    assert bump_speed("oci_speech", 1.0, 7) == 1.07

    audio = b"OggS-test-audio"
    payload = {
        "audioStream": repr(base64.b64encode(audio)),
        "markers": {
            "sentences": [
                {"words": [{"startTime": 0.96, "endTime": 1.2, "value": "Dupal"}]}
            ]
        },
    }
    decoded, words = parse_oci_response(payload, tempo=0.96)
    assert decoded == audio
    assert words == [{"t": 1.0, "w": "Dupal"}]
    print("Voice provider adapters are valid.")


if __name__ == "__main__":
    main()
