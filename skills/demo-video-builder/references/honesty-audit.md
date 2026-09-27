# Honesty audit: narration vs screen (v3)

Source narrations drift from what the recording actually shows. Before writing a single line, audit the
original script against the footage and log every contradiction. Typical findings:

| Narration says | Screen shows | Fix |
|---|---|---|
| a version number ("version four") | a different version in two places | speak no version |
| an accuracy figure | a training metric with no baseline | don't claim it; leave it visible, unhighlighted |
| "we import the model" | "already imported" | describe what is shown ("hands it over, checks the feature order") |
| result figures | the output cell is never on screen | drop them |
| "same numbers as before" | nothing to compare | replace with the product's own caveat |
| "in plain English" | the prompt names tables and functions | don't claim it |

## claims.json

Every figure or claim the narration makes gets one entry: the phrase **verbatim** from `vo_script.py`, and
the on-screen source (time + what's visible). `qa_film.py` fails if a phrase is missing from the narration
or has no source. Record what you dropped under `dropped_from_the_original_narration` so the owner sees why.

## Words to avoid unless the screen proves them

"plain English", "instantly", "100 % accurate", "guaranteed", "generally available", "available now",
competitor names, customer names. Put your list in `qa.json → banned_phrases`.
