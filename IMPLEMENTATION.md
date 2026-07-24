# 🛠️ Implementation Notes — What Was Built & Where

This document maps every graded task in the Engineering Handbook (`README.md`)
to the exact code that delivers it.

| Task | Points | Status |
| --- | --- | --- |
| 1. Dockerization & Deployment | 80 | ✅ Code complete |
| 2. Podcast parsing + perfect pronunciation | 30 | ✅ Code complete |
| 3. AI audio training pipeline (noise + silence) | 50 | ✅ Code complete |
| 4. Final 5-minute video | 40 | 📋 Manual — see `TASK4_GUIDE.md` |

---

## 🐳 Task 1 — Dockerization (80 pts)
**Files:** [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml),
[`.dockerignore`](.dockerignore), [`requirements.txt`](requirements.txt),
[`DOCKER.md`](DOCKER.md)

- One command runs everything: `docker compose up --build` → http://localhost:7860.
- `python:3.11-slim` base (the handbook warns 3.12+ breaks the AI libs).
- FFmpeg + libsndfile installed in the image, so users never install them by hand.
- **CPU-only PyTorch by default** for portability (no NVIDIA runtime required);
  a GPU path is documented in `DOCKER.md`.
- **Volumes** persist `saved_voices/`, `rvc_models/`, `training_data/`, and
  `hf_cache/` — turning the container off does **not** lose saved voices, and
  downloaded model weights are cached across runs.
- Fixed the broken `requirements.txt`: removed `TTS` (Coqui — needs C++ build
  tools and was the cause of the red build-tools crash) and replaced it with the
  package the app actually uses, `f5-tts`, plus the real runtime deps.

### Cross-platform fixes required for Docker (in `app.py`)
The original app hardcoded Windows-only paths (`venv\Scripts\edge-tts.exe`) and
bound to `127.0.0.1`, so it could never run in a Linux container.
- `_find_executable()` / `_find_rvc_python()` resolve tools from `PATH` first
  (Docker), then Windows `venv\Scripts\*.exe`, then Linux `venv/bin/*`.
- Server host/port and browser-open are now env-driven
  (`GRADIO_SERVER_NAME`, `GRADIO_SERVER_PORT`, `IN_DOCKER`), so the *same* code
  serves local dev (`127.0.0.1`, opens a browser) and Docker (`0.0.0.0`, headless).
- Logo path now resolves `assets/LOGO.jpg` (with a root fallback).

---

## 🎯 Task 2 — Podcast Parsing + Perfect Pronunciation (30 pts)
**File:** [`app.py`](app.py) — `parse_podcast_script`, `detect_language`,
`_gen_hindi_line`, `_gen_english_line`, `_stitch_segments`, `generate_podcast`.

### Crash-proof parsing
`parse_podcast_script()` was rewritten to never crash:
- Tolerates **any spacing around the colon** (`NARUTO:`, `NARUTO :`, `NARUTO   :`)
  and both ASCII `:` and full-width `：`.
- Supports **names with spaces / hyphens** (`Iron Man`, `Obi-Wan`).
- Lines **without** a speaker label are treated as **continuations** of the
  previous speaker (so multi-line dialogue works).
- A sentence that merely *contains* a colon (`Well, technically: ...`) is **not**
  mistaken for a speaker (validated by `_looks_like_speaker`).
- Unknown characters / malformed lines produce **polite warnings** in the log
  instead of a server crash.
- Character↔voice matching is normalized (`_norm_key`) so `Iron Man` matches a
  voice saved as `Iron_Man`, case-insensitively.

### Perfect pronunciation routing (the "Hybrid System")
`detect_language()` classifies each line as English or Hindi/Urdu
(Devanagari detection + a conservative romanized-Hindi heuristic; a manual
**Language Routing** control — Auto / English / Hindi-Urdu — is also on the tab).

For a **Hindi/Urdu** line, `_gen_hindi_line()` implements exactly the handbook's
hybrid: **Microsoft Neural base first, then clone into the character.**
1. Transliterate Roman → Devanagari (`transliterate.py`).
2. Generate a **perfectly pronounced** Microsoft Neural base with `edge-tts`.
3. Morph that base into the character's timbre with **RVC** (voice conversion,
   which preserves the native pronunciation).
4. If no RVC model exists for the character, **gracefully fall back** to the
   Neural base (still perfect pronunciation) — the app never crashes.

English lines continue to use F5-TTS cloning as before.

### Smooth audio
`_stitch_segments()` replaces the old hard `seg + silence + seg` concatenation
with per-clip fade-in/out **plus short crossfades** across the pauses, removing
the "sudden robotic silences" between lines.

---

## 🧠 Task 3 — AI Audio Training Pipeline (50 pts)
**File:** [`app.py`](app.py) — `preprocess_training_audio`, `_reduce_noise`,
`_remove_silence`, `_next_session_dir`.

The existing pipeline (chunk + normalize) crashed on messy audio and had no
cleaning. Added the two required filters:

- **The Noise Filter** (`_reduce_noise`) — a spectral noise gate via
  `noisereduce` that strips background static / hum / music bleed **before**
  chunking. Wrapped so a missing library or odd input degrades gracefully
  instead of crashing.
- **The Silence Cutter** (`_remove_silence`) — uses `pydub.silence.detect_nonsilent`
  to detect and remove "dead air", keeping a small pad around speech so cuts stay
  natural. The threshold is a UI slider.

New processing order: **mono/16 kHz → noise filter → silence cut → normalize →
chunk → export**. The log now reports how much dead air was removed and the clean
speech duration. Session folders use `_next_session_dir()` (no more collisions
from `len(os.listdir(...))`). The UI gained a **Noise Filter** toggle and a
**Silence Threshold** slider.

---

## 🎥 Task 4 — Final Video (40 pts)
Manual. Full step-by-step walkthrough (gather data → preprocess → save voices →
write script → generate → record) is in [`TASK4_GUIDE.md`](TASK4_GUIDE.md).

---

## ✅ Verification done
- `python -m py_compile app.py` — passes.
- Standalone unit tests for the pure-Python logic (parser edge cases, name
  normalization, language auto-detection, forced modes, transliteration, and
  empty/junk-input safety) — all pass without exceptions.
- Heavy ML paths (F5-TTS, RVC, Whisper) require the full model stack and are
  exercised by running the app (locally or via Docker).
