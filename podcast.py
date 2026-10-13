#!/usr/bin/env python3
"""
Record an issue's two-host script as one MP3 with chapter marks, using ElevenLabs.

Every turn is synthesised in its speaker's voice, then the pieces are joined
with ffmpeg; a chapter starts wherever a new segment does. Returns None (and
says why) if anything fails, so a missing podcast never blocks an issue.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1/text-to-speech"
VOICES = {
    "A": os.getenv("ELEVENLABS_VOICE_A", "JBFqnCBsd6RMkjVDRZzb"),
    "B": os.getenv("ELEVENLABS_VOICE_B", "EXAVITQu4vr4xnSDxMaL"),
}
TTS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")


def _speak(text, voice, path, key):
    """Synthesise one turn; returns the credits ElevenLabs charged for it."""
    resp = requests.post(
        f"{API}/{voice}?output_format=mp3_44100_128",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"text": text, "model_id": TTS_MODEL},
        timeout=180,
    )
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", {})
            reason = f"{detail.get('code') or detail.get('status')}: {detail.get('message')}"
        except Exception:
            reason = resp.text[:200]
        raise RuntimeError(f"ElevenLabs HTTP {resp.status_code} ({reason})")
    path.write_bytes(resp.content)
    return int(resp.headers.get("character-cost", 0) or 0)


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def make_podcast(segments, out_path):
    """segments: [{id, turns: [{speaker, text}]}]. Writes out_path; returns {duration, chapters, credits} or None."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        print("  podcast skipped: ELEVENLABS_API_KEY is not set")
        return None
    turns = [(seg["id"], turn["speaker"], turn["text"].strip()) for seg in segments for turn in seg["turns"]
             if turn["text"].strip()]
    if not turns:
        print("  podcast skipped: empty script")
        return None
    print(f"  podcast: {sum(len(t) for _, _, t in turns)} characters in {len(turns)} turns")
    credits = 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            chapters, clock, parts, current = [], 0.0, [], None
            for i, (segment, speaker, text) in enumerate(turns):
                part = tmp / f"{i:03d}.mp3"
                credits += _speak(text, VOICES[speaker], part, key)
                if segment != current:
                    chapters.append({"id": segment, "t": round(clock, 1)})
                    current = segment
                clock += _duration(part)
                parts.append(part)
            listing = tmp / "list.txt"
            listing.write_text("".join(f"file '{p}'\n" for p in parts))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                            "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)], check=True)
        print(f"  podcast: {credits} ElevenLabs credits used")
        return {"duration": round(_duration(out_path), 1), "chapters": chapters, "credits": credits}
    except Exception as e:
        print(f"  podcast skipped after {credits} credits: {e}")
        return None
