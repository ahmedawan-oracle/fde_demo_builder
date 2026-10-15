#!/usr/bin/env python3
"""Deterministic checks for the optional OCI Speech adapter."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "demo-video-builder" / "scripts"))

from tts_providers import bump_speed, normalize_voice, parse_oci_response  # noqa: E402
import tts_providers


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
    tts_providers._speech_verifiers["small.en"] = SimpleNamespace(
        transcribe=lambda path, **options: ([SimpleNamespace(text="Dupal service teams act sooner.")], None)
    )
    with patch.dict(os.environ, {"FDE_WHISPER_MODEL_PATH": ""}):
        tts_providers.verify_audio_content("Dupal service teams act sooner.", "unused.mp3")
        try:
            tts_providers.verify_audio_content("Our notebook builds a scored district summary.", "unused.mp3")
        except RuntimeError:
            pass
        else:
            raise AssertionError("Mismatched speech was accepted")
    tts_providers._speech_verifiers.clear()

    loaded = []
    def model_factory(name, **options):
        loaded.append((name, options))
        return object()

    with tempfile.TemporaryDirectory() as work:
        with patch.dict(os.environ, {"FDE_WHISPER_MODEL_PATH": work}), patch.dict(
            sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=model_factory)}
        ):
            assert tts_providers.speech_verifier("en-US") is tts_providers.speech_verifier("en-US")
            assert loaded == [(work, {"device": "cpu", "compute_type": "int8"})]
        with patch.dict(os.environ, {"FDE_WHISPER_MODEL_PATH": str(Path(work) / "missing")}):
            try:
                tts_providers.speech_verifier("en-US")
            except ValueError:
                pass
            else:
                raise AssertionError("Missing pinned ASR directory silently fell back")

        commands = []
        def run(command, **options):
            commands.append(command)
            if command[0] == "oci":
                Path(command[command.index("--file") + 1]).write_text(json.dumps(payload))
            return SimpleNamespace(returncode=0, stdout="2.0", stderr="")

        with patch.dict(os.environ, {"OCI_CLI_CONFIG_FILE": "env config", "OCI_CLI_PROFILE": "TEAM"}):
            inherited = normalize_voice({"provider": "oci_speech", "voice": "Brian"})
            assert inherited["config_file"] == "env config" and inherited["profile"] == "TEAM"
            explicit = normalize_voice({"provider": "oci_speech", "voice": "Brian", "profile": "DEMO",
                                        "config_file": "custom config", "auth": "security_token", "region": "example"})
        with patch.object(tts_providers.subprocess, "run", side_effect=run), patch.object(
            tts_providers, "verify_audio_content"
        ) as verify:
            tts_providers._render_oci("A verified result", explicit, 1.0, str(Path(work) / "audio.mp3"))
            verify.assert_called_once()
        for flag, value in (("--config-file", "custom config"), ("--profile", "DEMO"),
                            ("--auth", "security_token"), ("--region", "example")):
            assert commands[0][commands[0].index(flag) + 1] == value
    tts_providers._speech_verifiers.clear()
    print("Voice provider adapters are valid.")


if __name__ == "__main__":
    main()
