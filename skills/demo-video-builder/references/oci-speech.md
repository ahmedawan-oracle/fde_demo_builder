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

Before production, list available voices in the engagement region and synthesize one non-sensitive audition line:

```bash
oci speech voice list --profile DEFAULT --model-name TTS_2_NATURAL --language-code en-US --all
python gen_vo_multivoice.py audition  # first define an audition scene in vo_script.py
```

Record the provider, model, voices, profile name, approval, and generated-audio provenance in the media ledger. Do not
record OCI config contents, private keys, tenancy identifiers, or request receipts in the project. OCI Speech's
official TTS guide is https://docs.oracle.com/en-us/iaas/Content/speech/using/using-tts.htm.
