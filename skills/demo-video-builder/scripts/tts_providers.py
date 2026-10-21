#!/usr/bin/env python3
"""Voice-provider adapters for FDE multi-voice narration."""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import os
import subprocess
import tempfile
import re
from difflib import SequenceMatcher
from pathlib import Path

_speech_verifiers = {}


def speech_verifier(language: str):
    model_path = os.environ.get("FDE_WHISPER_MODEL_PATH")
    if model_path and not Path(model_path).is_dir():
        raise ValueError("FDE_WHISPER_MODEL_PATH must be an existing local model directory")
    model_name = model_path or ("small.en" if language.startswith("en") else "small")
    if model_name not in _speech_verifiers:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError("Narration verification requires faster-whisper") from exc
        _speech_verifiers[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _speech_verifiers[model_name]


def verify_audio_content(text: str, path: str, language: str = "en-US") -> None:
    """Reject valid audio containers that contain garbled synthesis."""
    verifier = speech_verifier(language)
    segments, _ = verifier.transcribe(path, beam_size=5, vad_filter=False,
                                     language=language.split("-")[0])
    recognized = " ".join(segment.text.strip() for segment in segments)
    normalize = lambda value: re.sub(r"[^\w]+", " ", value.casefold()).strip()
    score = SequenceMatcher(None, normalize(text), normalize(recognized), autojunk=False).ratio()
    if score < 0.80:
        raise RuntimeError(f"Narration contains unintelligible or mismatched audio (content score {score:.2f})")


def normalize_voice(raw: object) -> dict[str, object]:
    """Accept the original Edge tuple or an explicit provider dictionary."""
    if isinstance(raw, (tuple, list)) and len(raw) == 2:
        return {"provider": "edge", "voice": str(raw[0]), "speed": str(raw[1])}
    if not isinstance(raw, dict):
        raise ValueError("voice must be an Edge (voice, rate) pair or a provider dictionary")
    provider = str(raw.get("provider", "edge")).lower()
    if provider == "edge":
        return {
            "provider": provider,
            "voice": str(raw["voice"]),
            "speed": str(raw.get("rate", "+0%")),
        }
    if provider == "oci_speech":
        tempo = float(raw.get("tempo", 1.0))
        if not 0.75 <= tempo <= 1.25:
            raise ValueError("OCI Speech tempo must be between 0.75 and 1.25")
        return {
            "provider": provider,
            "voice": str(raw["voice"]),
            "speed": tempo,
            "profile": str(raw.get("profile", os.environ.get("OCI_CLI_PROFILE", "DEFAULT"))),
            "config_file": raw.get("config_file", os.environ.get("OCI_CLI_CONFIG_FILE")),
            "region": raw.get("region"),
            "auth": raw.get("auth"),
            "language": str(raw.get("language", "en-US")),
            "model": str(raw.get("model", "TTS_2_NATURAL")),
        }
    raise ValueError(f"unsupported voice provider: {provider}")


def bump_speed(provider: str, speed: object, percent: int) -> object:
    if provider == "edge":
        return f"{int(str(speed).rstrip('%')) + percent:+d}%"
    return min(1.25, round(float(speed) * (1 + percent / 100), 4))


def parse_oci_response(payload: dict[str, object], tempo: float = 1.0) -> tuple[bytes, list[dict[str, object]]]:
    """Decode OCI's JSON audio stream and normalize its word marks."""
    encoded = payload.get("audioStream")
    if not isinstance(encoded, (str, bytes)):
        raise RuntimeError("OCI Speech response has no audioStream")
    if isinstance(encoded, str) and encoded.startswith(("b'", 'b"')):
        encoded = ast.literal_eval(encoded)
    if isinstance(encoded, str):
        encoded = encoded.encode("ascii")
    audio = base64.b64decode(encoded, validate=True)
    sentences = payload.get("markers", {}).get("sentences", [])  # type: ignore[union-attr]
    words = [
        {"t": round(float(word["startTime"]) / tempo, 3), "w": str(word["value"])}
        for sentence in sentences
        for word in sentence.get("words", [])
    ]
    if not audio or not words:
        raise RuntimeError("OCI Speech response is missing audio or word marks")
    return audio, words


def _render_oci(text: str, voice: dict[str, object], speed: float, path: str) -> list[dict[str, object]]:
    config = {
        "modelFamily": "ORACLE",
        "modelDetails": {
            "modelName": voice["model"],
            "voiceId": voice["voice"],
            "languageCode": voice["language"],
        },
        "speechSettings": {
            "outputFormat": "JSON",
            "sampleRateInHz": 24000,
            "speechMarkTypes": ["WORD", "SENTENCE"],
            "textType": "TEXT",
        },
    }
    with tempfile.TemporaryDirectory(prefix="fde-oci-speech-") as work:
        response = Path(work) / "response.json"
        source = Path(work) / "voice.ogg"
        cmd = [
            "oci", "speech", "synthesize-speech",
            "--profile", str(voice["profile"]),
            "--text", text,
            "--file", str(response),
            "--configuration", json.dumps(config, separators=(",", ":")),
        ]
        if voice.get("config_file"):
            cmd += ["--config-file", str(voice["config_file"])]
        if voice.get("region"):
            cmd += ["--region", str(voice["region"])]
        if voice.get("auth"):
            cmd += ["--auth", str(voice["auth"])]
        response_call = subprocess.run(cmd, capture_output=True, text=True)
        if response_call.returncode:
            try:
                error = json.loads(response_call.stderr.split("ServiceError:", 1)[-1].strip())
                code = str(error.get("code", "RequestFailed"))
            except (ValueError, TypeError):
                code = "RequestFailed"
            detail = (response_call.stderr or "").strip().replace("\n", " ")[-300:]
            raise RuntimeError(f"OCI Speech failed: {code}; verify the selected profile, region and voice"
                               + (f" ({detail})" if detail else ""))
        audio, words = parse_oci_response(json.loads(response.read_text(encoding="utf-8")), speed)
        source.write_bytes(audio)
        ffmpeg = ["ffmpeg", "-y", "-i", str(source)]
        if abs(speed - 1.0) > 1e-6:
            ffmpeg += ["-af", f"atempo={speed:.4f}"]
        ffmpeg += ["-c:a", "libmp3lame", "-q:a", "2", path]
        subprocess.run(ffmpeg, check=True, capture_output=True)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            check=True, capture_output=True, text=True,
        )
        duration = float(result.stdout.strip())
        if any(float(word["t"]) < 0 or float(word["t"]) >= duration for word in words):
            raise RuntimeError("OCI Speech word offsets fall outside the decoded audio duration")
        verify_audio_content(text, path, str(voice["language"]))
    return words


async def render_voice(
    text: str,
    voice: dict[str, object],
    speed: object,
    path: str,
    tries: int = 4,
) -> list[dict[str, object]]:
    """Render a phrase and return word offsets relative to that phrase."""
    if voice["provider"] == "oci_speech":
        await asyncio.to_thread(speech_verifier, str(voice["language"]))
    for attempt in range(tries):
        try:
            if voice["provider"] == "oci_speech":
                return await asyncio.to_thread(_render_oci, text, voice, float(speed), path)

            import edge_tts

            words: list[dict[str, object]] = []
            audio = b""
            communicate = edge_tts.Communicate(text, str(voice["voice"]), rate=str(speed), boundary="WordBoundary")
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
                elif chunk["type"] == "WordBoundary":
                    words.append({"t": round(chunk["offset"] / 1e7, 3), "w": chunk["text"]})
            if not audio or not words:
                raise RuntimeError("Edge TTS returned no audio or word marks")
            Path(path).write_bytes(audio)
            return words
        except Exception:
            if attempt == tries - 1:
                raise
            print(f"  retry {attempt + 1} for {Path(path).name}")
            await asyncio.sleep(2 * (attempt + 1))

    raise AssertionError("unreachable")
