# vo_script.example.py (v3 film) — the narration that drives film.example.html. Copy to vo_script.py.
#
# Everything is FICTIONAL ("Acme", synthetic numbers) and matches make_sample_recording.py.
# One SCENE = the whole film: the phases play back-to-back and ARE the clock. Every cut, scroll, push,
# highlight and typed word in the film is keyed to a word spoken here (wt(phase, word)).
#
# Voices: 3–4 is the sweet spot for a booth film (narrator + persona voices). Speak the question on screen
# EXACTLY as it is typed, so the glyph reveal can follow the voice word for word.
VOICES = {
    "narrator":  ("en-US-AndrewNeural",      "+4%"),   # the story, the turns, the close
    "analyst":   ("en-US-AvaNeural",         "+5%"),   # first person: the notebook
    "lead":      ("en-US-ChristopherNeural", "+0%"),   # first person: the business question
    "assistant": ("en-US-BrianNeural",       "+2%"),   # the product's own voice (+8 % read 3.5 words/s — too fast for the text gate)
}

SCENES = {
    "film": {
        "gap": 0.45,
        "pad": 0.10,
        "phases": [
            {"name": "hook", "voice": "narrator", "text":
             "Every Monday, the operations lead at Acme asks the same question. And every Monday, it takes a day to answer."},
            {"name": "title", "voice": "narrator", "text":
             "Acme is fictional, and so is its data. The workflow is the point."},
            {"name": "nb", "voice": "analyst", "text":
             "My notebook loads the orders, filters the late deliveries, and counts them by region."},
            {"name": "ask", "voice": "lead", "text":
             "Which regions missed their on-time delivery target last week?"},
            {"name": "answer", "voice": "assistant", "text":
             "I send the question, and the answer comes back from the same governed data."},
            {"name": "close", "voice": "narrator", "text":
             "One notebook. One question. One answer the whole team can trust."},
        ],
    },
}

PLACED = {}
