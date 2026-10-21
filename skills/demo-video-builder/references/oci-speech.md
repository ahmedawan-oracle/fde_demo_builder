# OCI Speech narration

Use OCI Speech only when the engagement approves cloud TTS and the narration text may be sent to the selected OCI
tenancy. Edge TTS also sends text to a cloud service and needs the corresponding approval. An approved prerecorded
human voice or local TTS is the offline fallback. Never switch providers silently.

`gen_vo_multivoice.py` accepts the original Edge tuple and an OCI provider dictionary in the same `VOICES` map:

```python
VOICES = {
    "narrator": {
        "provider": "oci_speech",
        "voice": "Annabelle",
        "profile": "DEFAULT",
        "language": "en-US",
        "model": "TTS_2_NATURAL",
        "tempo": 0.96,
    },
    "guide": {
        "provider": "oci_speech",
        "voice": "Brian",
        "profile": "DEFAULT",
        "language": "en-US",
        "model": "TTS_2_NATURAL",
    },
    "edge_alternative": ("en-US-AvaNeural", "+3%"),
}
```

The provider calls the profile-based OCI CLI, requests JSON output with word and sentence speech marks, decodes the
embedded audio, and writes the same MP3 and word-timing artifacts as Edge TTS. `tempo` is an optional pitch-preserving
post-process from `0.75` to `1.25`; use it sparingly. A placed beat may increase tempo to fit its budget, but a line
that still overruns after two bumps must be rewritten.

Set optional `config_file` in each OCI voice dictionary when the brief selects a non-default OCI configuration
file; it is passed as `--config-file`. Otherwise the adapter honors `OCI_CLI_CONFIG_FILE` when set, preserving
the CLI's normal default when neither is supplied. Keep profile, auth and region aligned with the verified target.

Install `faster-whisper` in the project's Python environment when selecting OCI narration. The adapter loads its
local `small.en` recognition model for English, or `small` for other languages, and checks the actual rendered speech
before accepting a take. Model initialization happens before any synthesis request. The first use downloads the
recognition weights from Hugging Face; prefetch them during setup when offline production is needed.
For pinned/offline production set `FDE_WHISPER_MODEL_PATH` to the existing downloaded model directory. The adapter
loads that path directly and fails if it is missing; it never silently substitutes an unpinned model. Select a
language-compatible model. `verify_audio_content(text, path, language)` can also verify local/Edge takes and final
mixed narration; it does not synthesize speech or send narration to another provider.
OCI can return a valid audio file and plausible speech marks while the audio is garbled;
container, timing and loudness checks do not establish intelligibility. Rejected takes are retried within the
existing four-attempt limit. Compare the final mixed speech to the script as well, including spoken figures and
acronyms; a transcript similarity score is a rejection aid rather than a substitute for listening.
Spell acronyms and amounts for speech and inspect legitimate recognition mismatches instead of weakening the gate.

Before production, list available voices in the engagement region and synthesize one non-sensitive audition line:

```bash
oci speech voice list --profile DEFAULT --model-name TTS_2_NATURAL --language-code en-US --all
python gen_vo_multivoice.py audition  # first define an audition scene in vo_script.py
```

Record the provider, model, voices, profile name, approval, and generated-audio provenance in the media ledger. Do not
record OCI config contents, private keys, tenancy identifiers, or request receipts in the project. OCI Speech's
official TTS guide is https://docs.oracle.com/en-us/iaas/Content/speech/using/using-tts.htm.
