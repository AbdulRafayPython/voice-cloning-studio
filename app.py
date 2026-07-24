import os
os.environ["NUMBA_DISABLE_JIT"] = "1"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["HF_HOME"] = os.environ.get("HF_HOME", os.path.join(BASE_DIR, "hf_cache"))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
os.environ["TEMP"] = TEMP_DIR
os.environ["TMP"] = TEMP_DIR
import tempfile
tempfile.tempdir = TEMP_DIR

import sys
import re
import shutil
import subprocess
import gradio as gr
from pydub import AudioSegment

from transliterate import roman_to_devanagari

SAVED_VOICES_DIR = os.path.join(BASE_DIR, "saved_voices")
os.makedirs(SAVED_VOICES_DIR, exist_ok=True)


# ─── Cross-platform executable resolution ──────────────────────────────
# Locally the app runs from a Windows virtualenv (venv\Scripts\*.exe).
# Inside Docker (Linux) the same tools are installed on PATH. Resolve both
# so a single codebase works on Windows, macOS, Linux and containers.
def _find_executable(name, venv_subdir="venv"):
    on_path = shutil.which(name)
    if on_path:
        return on_path
    win = os.path.join(BASE_DIR, venv_subdir, "Scripts", name + ".exe")
    if os.path.exists(win):
        return win
    nix = os.path.join(BASE_DIR, venv_subdir, "bin", name)
    if os.path.exists(nix):
        return nix
    return name  # fall back to bare name; resolved from PATH at call time


def _find_rvc_python():
    win = os.path.join(BASE_DIR, "rvc_venv", "Scripts", "python.exe")
    if os.path.exists(win):
        return win
    nix = os.path.join(BASE_DIR, "rvc_venv", "bin", "python")
    if os.path.exists(nix):
        return nix
    # No dedicated RVC venv (e.g. single-env Docker image) -> use current python
    return sys.executable


EDGE_TTS_EXE = _find_executable("edge-tts")
F5_TTS_EXE = _find_executable("f5-tts_infer-cli")
RVC_MODELS_DIR = os.path.join(BASE_DIR, "rvc_models")
RVC_PYTHON_EXE = _find_rvc_python()
RVC_INFER_SCRIPT = os.path.join(BASE_DIR, "rvc_infer.py")
os.makedirs(RVC_MODELS_DIR, exist_ok=True)

# ─── Utility: Run edge-tts via subprocess (avoids asyncio conflicts with Gradio) ───
def run_edge_tts(text, voice, output_path, rate=None, pitch=None):
    """Generate TTS audio using edge-tts CLI. Returns (ok, stderr)."""
    cmd = [EDGE_TTS_EXE, "--voice", voice, "--text", text, "--write-media", output_path]
    if rate:
        cmd += ["--rate", rate]
    if pitch:
        cmd += ["--pitch", pitch]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    return result.returncode == 0, result.stderr

# ─── Voice Library ───
def get_saved_voices():
    voices = []
    if os.path.exists(SAVED_VOICES_DIR):
        for d in sorted(os.listdir(SAVED_VOICES_DIR)):
            if os.path.isdir(os.path.join(SAVED_VOICES_DIR, d)):
                voices.append(d)
    return voices

def load_voice(name):
    if not name:
        return None, ""
    audio_path = os.path.join(SAVED_VOICES_DIR, name, "audio.wav")
    text_path = os.path.join(SAVED_VOICES_DIR, name, "text.txt")
    text = ""
    if os.path.exists(text_path):
        with open(text_path, "r", encoding="utf-8") as f:
            text = f.read()
    if not os.path.exists(audio_path):
        return None, text
    return audio_path, text

def save_voice(name, audio_path, text):
    if not name or not audio_path:
        return "❌ Provide a name AND audio file.", gr.update(), gr.update(), gr.update(), gr.update()
    name = name.strip().replace(" ", "_")
    voice_dir = os.path.join(SAVED_VOICES_DIR, name)
    os.makedirs(voice_dir, exist_ok=True)
    shutil.copy(audio_path, os.path.join(voice_dir, "audio.wav"))
    with open(os.path.join(voice_dir, "text.txt"), "w", encoding="utf-8") as f:
        f.write(text or "")
    choices = get_saved_voices()
    return f"✅ Voice '{name}' saved!", gr.update(choices=choices, value=name), gr.update(choices=choices), gr.update(choices=choices), gr.update(choices=choices)

def delete_voice(name):
    if not name:
        return "Select a voice first.", gr.update(), gr.update(), gr.update(), gr.update()
    voice_dir = os.path.join(SAVED_VOICES_DIR, name)
    if os.path.exists(voice_dir):
        shutil.rmtree(voice_dir)
    choices = get_saved_voices()
    return f"🗑️ Deleted '{name}'", gr.update(choices=choices, value=None), gr.update(choices=choices), gr.update(choices=choices), gr.update(choices=choices)

# ─── RVC Backend ───
def get_rvc_models():
    models = []
    if os.path.exists(RVC_MODELS_DIR):
        for f in os.listdir(RVC_MODELS_DIR):
            if f.endswith(".pth"):
                models.append(f)
    return models

def run_rvc_conversion(input_audio, model_name, pitch):
    if not input_audio: return None, "Please upload a reference audio."
    if not model_name: return None, "Please select an RVC model (.pth)."

    model_path = os.path.join(RVC_MODELS_DIR, model_name)
    output_path = os.path.join(BASE_DIR, "rvc_output.wav")

    cmd = [
        RVC_PYTHON_EXE, RVC_INFER_SCRIPT,
        "--model", model_path,
        "--input", input_audio,
        "--output", output_path,
        "--pitch", str(int(pitch)),
        "--method", "rmvpe"
    ]

    # Try finding an index file with the same name
    index_path = model_path.replace(".pth", ".index")
    if os.path.exists(index_path):
        cmd += ["--index", index_path]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode == 0 and os.path.exists(output_path):
        return output_path, "✅ Voice converted successfully!"
    else:
        return None, f"❌ RVC Error:\n{result.stdout}\n{result.stderr}"

# ─── F5-TTS Core Engine ───
def run_f5tts(text, ref_audio_path, ref_text, output_name="output_cloned.wav"):
    output_path = os.path.join(BASE_DIR, output_name)
    trimmed = os.path.join(TEMP_DIR, "trimmed_ref_gen.wav")

    audio = AudioSegment.from_file(ref_audio_path)
    if len(audio) > 8000:
        audio = audio[:8000]
    audio.export(trimmed, format="wav")

    if os.path.exists(output_path):
        os.remove(output_path)

    # Prevent internal F5-TTS whisper from hanging on low VRAM
    if not ref_text or not ref_text.strip():
        # define a dummy progress to pass to extract_text_fn
        class DummyProgress:
            def __call__(self, *args, **kwargs): pass
        ref_text = extract_text_fn(trimmed, progress=DummyProgress())
        if ref_text.startswith("Error"):
            return None, f"Failed to transcribe reference audio: {ref_text}"

    import tomli_w
    config_path = os.path.join(BASE_DIR, "inference_config.toml")
    config_dict = {
        "model": "F5TTS_Base", "ref_audio": trimmed,
        "ref_text": ref_text.strip(),
        "speed": 1.0, "nfe_step": 16, "gen_text": text,
        "output_dir": BASE_DIR, "output_file": output_name, "voices": {}
    }
    with open(config_path, "wb") as f:
        tomli_w.dump(config_dict, f)

    env = os.environ.copy()
    env.update({"TEMP": TEMP_DIR, "TMP": TEMP_DIR, "NUMBA_DISABLE_JIT": "1",
                "HF_HOME": os.environ["HF_HOME"], "PYTHONIOENCODING": "utf-8"})

    result = subprocess.run([F5_TTS_EXE, "-c", config_path],
        capture_output=True, text=True, encoding='utf-8', env=env)

    if result.returncode != 0:
        return None, f"CLI Error: {result.stderr[-500:]}"

    if os.path.exists(output_path):
        import soundfile as sf
        import numpy as np
        data, sr = sf.read(output_path)
        std = np.std(data)
        if std < 0.001:
            return None, "Output is silent. Try different reference audio."
        return output_path, f"✅ Generated {len(data)/sr:.1f}s audio"

    import glob
    wavs = glob.glob(os.path.join(BASE_DIR, "infer_cli_*.wav"))
    if wavs:
        latest = max(wavs, key=os.path.getmtime)
        return latest, f"✅ Found: {os.path.basename(latest)}"
    return None, "❌ Output file not found!"

# ─── Tab 1: Standard Clone ───
def clone_voice_tab1(text, ref_text, audio_ref, progress=gr.Progress()):
    if not text: return None, "Enter text to generate."
    if not audio_ref: return None, "Upload a reference audio."
    progress(0.2, desc="Processing reference...")
    progress(0.4, desc="Running F5-TTS (1-3 min)...")
    path, log = run_f5tts(text, audio_ref, ref_text)
    progress(1.0)
    return path, log

# ─── Tab 2: Dramatic Story Mode ───
NARRATOR_VOICES = {
    "Guy (Passionate Male)": "en-US-GuyNeural",
    "Christopher (Authority Male)": "en-US-ChristopherNeural",
    "Andrew (Confident Male)": "en-US-AndrewNeural",
    "Eric (Rational Male)": "en-US-EricNeural",
    "Brian (Casual Male)": "en-US-BrianNeural",
    "Jenny (Friendly Female)": "en-US-JennyNeural",
    "Aria (Confident Female)": "en-US-AriaNeural",
    "Ava (Expressive Female)": "en-US-AvaNeural",
    "Ryan (British Male)": "en-GB-RyanNeural",
    "Sonia (British Female)": "en-GB-SoniaNeural",
}

# Microsoft Neural voices that produce native Hindi/Urdu pronunciation.
HINDI_URDU_VOICES = [
    "hi-IN-MadhurNeural", "hi-IN-SwaraNeural",
    "ur-PK-AsadNeural", "ur-PK-UzmaNeural",
    "ur-IN-SalmanNeural", "ur-IN-GulNeural",
]

def dramatic_clone(text, saved_voice_name, narrator_style, progress=gr.Progress()):
    if not text:
        return None, None, "Enter a story script."
    if not saved_voice_name:
        return None, None, "Select a saved voice from your library first."

    log_lines = []

    # Step 1: Generate emotional narration via edge-tts
    progress(0.1, desc="Step 1: Generating dramatic narration...")
    voice_id = NARRATOR_VOICES.get(narrator_style, "en-US-GuyNeural")
    emotion_path = os.path.join(TEMP_DIR, "emotion_base.mp3")
    ok, err = run_edge_tts(text, voice_id, emotion_path)
    if not ok:
        return None, None, f"❌ Edge-TTS failed: {err}"
    log_lines.append(f"Step 1: ✅ Emotional narration generated ({narrator_style})")

    # Step 2: Clone into anime voice using F5-TTS
    progress(0.4, desc="Step 2: Cloning into anime voice (1-3 min)...")
    voice_audio, voice_text = load_voice(saved_voice_name)
    if not voice_audio:
        log_lines.append(f"Step 2: ⚠️ Voice '{saved_voice_name}' audio not found. Showing emotion base only.")
        return emotion_path, None, "\n".join(log_lines)

    clone_path, clone_log = run_f5tts(text, voice_audio, voice_text, "dramatic_clone.wav")
    log_lines.append(f"Step 2: {clone_log}")
    progress(1.0)
    return emotion_path, clone_path, "\n".join(log_lines)

# ─── Tab 3: Hindi/Urdu ───
def generate_hindi(text, voice_id, use_transliteration, speed, pitch, progress=gr.Progress()):
    if not text:
        return None, "Enter some text."

    status = []
    final_text = text

    if use_transliteration:
        if contains_devanagari(text):
            status.append("Text already in Devanagari.")
        else:
            final_text = roman_to_devanagari(text)
            status.append(f"🔄 Transliterated to: {final_text}")

    output_path = os.path.join(TEMP_DIR, "hindi_output.mp3")

    rate_arg = f"{speed:+d}%" if speed != 0 else None
    pitch_arg = f"{pitch:+d}Hz" if pitch != 0 else None

    progress(0.5, desc="Generating voice...")
    ok, err = run_edge_tts(final_text, voice_id, output_path, rate=rate_arg, pitch=pitch_arg)
    if not ok:
        return None, f"❌ Error: {err}"

    status.append("✅ Generated successfully!")
    progress(1.0)
    return output_path, "\n".join(status)

# ─── Extract Text (Whisper) ───
def extract_text_fn(audio_path, progress=gr.Progress()):
    if not audio_path: return "Upload an audio file first!"
    try:
        trimmed = os.path.join(TEMP_DIR, "extract_temp.wav")
        audio = AudioSegment.from_file(audio_path)
        if len(audio) > 8000: audio = audio[:8000]
        audio.export(trimmed, format="wav")
        progress(0.4, desc="Loading Whisper...")
        import torch
        from transformers import pipeline
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        pipe = pipeline("automatic-speech-recognition", model="openai/whisper-base",
                        device=device, torch_dtype=dtype)
        progress(0.7, desc="Transcribing...")
        result = pipe(trimmed, chunk_length_s=30, generate_kwargs={"task": "transcribe"})
        text = result['text'].strip()
        del pipe
        import gc; gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        return text
    except Exception as e:
        return f"Error: {str(e)}"

# ═══════════════════════════════════════════════════════════════════════
#  Language detection & routing helpers (Task 2: Perfect Pronunciation)
# ═══════════════════════════════════════════════════════════════════════
_DEVANAGARI_RE = re.compile(r'[ऀ-ॿ]')

# Strong Hindi/Urdu romanized markers that are NOT common English words.
# Used only for "Auto" detection; ambiguous words (me, do, he, to...) excluded.
_STRONG_HINDI_TOKENS = {
    "kya", "hai", "hain", "nahi", "nahin", "kaise", "kaisa", "kaisi", "haal",
    "bhai", "yaar", "acha", "accha", "theek", "zindagi", "duniya", "mohabbat",
    "pyar", "pyaar", "dost", "kahani", "sunao", "batao", "dekho", "chalo",
    "karo", "karna", "waqt", "shukriya", "namaste", "mera", "meri", "tera",
    "teri", "tumhara", "hamara", "kyun", "kyunki", "matlab", "bilkul", "zaroor",
    "insaan", "baat", "bahut", "bohot", "thoda", "sahi", "chahiye", "raha",
    "rahe", "rahi", "gaya", "gayi", "hoga", "hogi", "tumne", "maine", "unhone",
    "bh", "kaha", "suno", "arre", "abhi", "phir", "lekin", "magar", "isliye",
}


def contains_devanagari(text):
    return bool(_DEVANAGARI_RE.search(text or ""))


def _romanized_hindi_hits(text):
    words = re.findall(r"[A-Za-z']+", (text or "").lower())
    if not words:
        return 0, 0
    hits = sum(1 for w in words if w in _STRONG_HINDI_TOKENS)
    return hits, len(words)


def detect_language(text, mode="auto"):
    """Return 'hi' (Hindi/Urdu) or 'en'. `mode` forces the result when not 'auto'."""
    m = (mode or "auto").lower()
    if m.startswith("eng"):
        return "en"
    if m.startswith("hin") or m in ("hi", "urdu", "ur", "hindi/urdu"):
        return "hi"
    # Auto-detect
    if contains_devanagari(text):
        return "hi"
    hits, total = _romanized_hindi_hits(text)
    if hits >= 2 or (total > 0 and hits / total >= 0.34):
        return "hi"
    return "en"


def _norm_key(s):
    """Normalize a name for matching: 'Iron Man' / 'iron-man' -> 'iron_man'."""
    return re.sub(r"[\s\-]+", "_", (s or "").strip()).lower()


# ─── Tab 4: Multi-Voice Podcast (Task 2: crash-proof + perfect pronunciation) ───
def _looks_like_speaker(candidate):
    """A speaker label is short, punctuation-free, and only a few words."""
    c = (candidate or "").strip()
    if not c or len(c) > 40:
        return False
    if any(ch in c for ch in ".!?,;\"()"):
        return False
    return len(c.split()) <= 4


def parse_podcast_script(script_text):
    """
    Parse a script into ([(name, dialogue), ...], warnings).

    Crash-proof and tolerant of:
      - any spacing around the colon:  'NARUTO:', 'NARUTO :', 'NARUTO   :   '
      - ASCII and full-width colons:   ':' and '：'
      - names with spaces/hyphens:     'Iron Man', 'Obi-Wan'
      - continuation lines (no colon) that belong to the previous speaker
      - sentences that merely contain a colon (treated as continuation, not a speaker)

    Never raises: bad lines become warnings instead of crashing the server.
    """
    parsed = []          # list of [name, dialogue] (mutable for continuations)
    warnings = []
    sep_re = re.compile(r'^\s*(.+?)\s*[:：]\s*(.*)$')

    for lineno, raw in enumerate((script_text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue

        m = sep_re.match(line)
        if m and _looks_like_speaker(m.group(1)):
            name = m.group(1).strip()
            dialogue = m.group(2).strip()
            if not dialogue:
                warnings.append(f"Line {lineno}: '{name}' has no dialogue — skipped.")
                continue
            parsed.append([name, dialogue])
        else:
            # No usable speaker label -> continuation of previous speaker.
            if parsed:
                parsed[-1][1] += " " + line
            else:
                warnings.append(
                    f"Line {lineno}: no speaker found (expected 'NAME: text') — "
                    f"skipped: \"{line[:50]}\""
                )

    return [(n, d) for n, d in parsed], warnings


def _stitch_segments(segments, pause_ms, crossfade_ms=60):
    """Join clips with natural pauses and short crossfades (no robotic silences)."""
    clean = [s for s in segments if s is not None and len(s) > 0]
    if not clean:
        return None

    def _soft(seg):
        # Small fades remove clicks at the cut points; keep them shorter than the clip.
        f = min(15, len(seg) // 2)
        return seg.fade_in(f).fade_out(f) if f > 0 else seg

    faded = [_soft(s) for s in clean]
    pause = AudioSegment.silent(duration=max(0, int(pause_ms)))
    final = faded[0]
    for seg in faded[1:]:
        final = final + pause
        cf = max(0, min(crossfade_ms, len(seg) // 2, len(final) // 2))
        final = final.append(seg, crossfade=cf)
    return final


def _gen_english_line(dialogue, saved_voice_name, out_name):
    """English line -> F5-TTS clone of the saved anime voice."""
    if not saved_voice_name:
        return None, "no saved voice for this character"
    voice_audio, voice_text = load_voice(saved_voice_name)
    if not voice_audio:
        return None, f"audio file missing for '{saved_voice_name}'"
    return run_f5tts(dialogue, voice_audio, voice_text, output_name=out_name)


def _gen_hindi_line(dialogue, rvc_model, hindi_voice, idx):
    """
    Perfect-pronunciation route (the 'Hybrid System' from the handbook):
      1. Transliterate Roman -> Devanagari so the script is script-correct.
      2. Generate a *perfectly pronounced* Microsoft Neural base first.
      3. Clone that base into the anime character with RVC (voice-to-voice),
         which preserves the native pronunciation while swapping the timbre.
      4. If no RVC model exists for the character, fall back to the Neural
         base (still perfect pronunciation) so the app never crashes.
    Returns (path, note).
    """
    text = dialogue if contains_devanagari(dialogue) else roman_to_devanagari(dialogue)
    base_path = os.path.join(TEMP_DIR, f"pod_hi_base_{idx}.mp3")
    ok, err = run_edge_tts(text, hindi_voice, base_path)
    if not ok:
        return None, f"Neural base (edge-tts) failed: {err}"

    if rvc_model:
        rvc_out, rvc_log = run_rvc_conversion(base_path, rvc_model, 0)
        if rvc_out and os.path.exists(rvc_out):
            # Copy out of the shared rvc_output.wav so the next line can't clobber it.
            safe = os.path.join(TEMP_DIR, f"pod_hi_rvc_{idx}.wav")
            shutil.copy(rvc_out, safe)
            return safe, f"Neural base → RVC clone ({rvc_model})"
        return base_path, f"RVC failed ({str(rvc_log)[:60]}) — using Neural base"

    return base_path, "Neural base (add an RVC .pth model for anime timbre)"


def generate_podcast(script_text, pause_ms, lang_mode, hindi_voice, progress=gr.Progress()):
    if not script_text or not script_text.strip():
        return None, "Write a script first."

    parsed, warnings = parse_podcast_script(script_text)

    log_lines = []
    if warnings:
        log_lines.append("⚠️ Parser warnings:")
        log_lines.extend(f"   {w}" for w in warnings)
        log_lines.append("")

    if not parsed:
        return None, "\n".join(log_lines) + (
            "❌ Could not find any 'NAME: dialogue' lines.\n"
            "Use the format:\nNARUTO: Hey Luffy!\nLUFFY: Hey Naruto!"
        )

    # Per-line language decision (drives Neural-base routing for Hindi/Urdu).
    langs = [detect_language(d, lang_mode) for _, d in parsed]

    characters = list(dict.fromkeys(name for name, _ in parsed))
    saved_map = {_norm_key(v): v for v in get_saved_voices()}
    rvc_map_all = {_norm_key(os.path.splitext(f)[0]): f for f in get_rvc_models()}

    voice_map = {c: saved_map.get(_norm_key(c)) for c in characters}   # F5 (English)
    rvc_map = {c: rvc_map_all.get(_norm_key(c)) for c in characters}   # RVC (Hindi clone)

    # Only characters that speak an English line strictly require a saved voice.
    need_english = {c for (c, _), lang in zip(parsed, langs) if lang == "en"}
    missing = [c for c in need_english if not voice_map.get(c)]
    if missing:
        saved = list(saved_map.values())
        return None, "\n".join(log_lines) + (
            f"❌ These characters speak English lines but have no matching saved voice:\n"
            f"   {', '.join(missing)}\n\n"
            f"Your saved voices: {', '.join(saved) if saved else '(none yet)'}\n\n"
            f"Names match case-insensitively and ignore spaces/hyphens "
            f"(e.g. 'Iron Man' matches a voice saved as 'Iron_Man').\n"
            f"Go to the Voice Cloner tab to save voices first."
        )

    log_lines.append(f"📋 Parsed {len(parsed)} lines from {len(characters)} characters")
    for c in characters:
        bits = []
        if voice_map.get(c):
            bits.append(f"F5 voice '{voice_map[c]}'")
        if rvc_map.get(c):
            bits.append(f"RVC '{rvc_map[c]}'")
        log_lines.append(f"   {c} → {', '.join(bits) if bits else '(Neural base fallback)'}")

    # Generate each line
    audio_segments = []
    for i, (char, dialogue) in enumerate(parsed):
        lang = langs[i]
        progress((i + 1) / len(parsed),
                 desc=f"Generating line {i+1}/{len(parsed)} ({char}, {lang.upper()})...")
        log_lines.append(f"\n🎙️ [{i+1}/{len(parsed)}] {char} [{lang.upper()}]: \"{dialogue[:50]}...\"")

        if lang == "hi":
            path, note = _gen_hindi_line(dialogue, rvc_map.get(char), hindi_voice, i)
        else:
            path, note = _gen_english_line(dialogue, voice_map.get(char), f"podcast_line_{i}.wav")

        if path and os.path.exists(path):
            seg = AudioSegment.from_file(path)
            audio_segments.append(seg)
            log_lines.append(f"   ✅ {len(seg)/1000:.1f}s — {note}")
        else:
            log_lines.append(f"   ❌ Failed: {note}")

    if not audio_segments:
        return None, "\n".join(log_lines) + "\n\n❌ No audio was generated."

    # Stitch together with smooth pauses + crossfades
    log_lines.append(f"\n🔗 Stitching {len(audio_segments)} segments (smooth crossfades)...")
    final = _stitch_segments(audio_segments, pause_ms)
    if final is None:
        return None, "\n".join(log_lines) + "\n\n❌ Stitching produced empty audio."

    output_path = os.path.join(BASE_DIR, "podcast_output.wav")
    final.export(output_path, format="wav")
    log_lines.append(f"✅ Final podcast: {len(final)/1000:.1f}s total")

    return output_path, "\n".join(log_lines)

# ─── Audio Editor Functions ───
def edit_audio_trim(audio_path, start_s, end_s):
    if not audio_path: return None, "Upload audio first."
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)
        trimmed = audio[start_ms:end_ms]
        out = os.path.join(BASE_DIR, "edited_audio.wav")
        trimmed.export(out, format="wav")
        return out, f"✅ Trimmed: Kept {start_s}s to {end_s}s"
    except Exception as e:
        return None, f"❌ Error: {e}"

def edit_audio_cut(audio_path, start_s, end_s):
    if not audio_path: return None, "Upload audio first."
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)
        cut = audio[:start_ms] + audio[end_ms:]
        out = os.path.join(BASE_DIR, "edited_audio.wav")
        cut.export(out, format="wav")
        return out, f"✅ Cut: Removed {start_s}s to {end_s}s"
    except Exception as e:
        return None, f"❌ Error: {e}"

def edit_audio_replace(audio_path, start_s, end_s, text, voice_name, progress=gr.Progress()):
    if not audio_path: return None, "Upload audio first."
    if not text: return None, "Enter text to generate."
    if not voice_name: return None, "Select a voice."
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)

        voice_audio, voice_text = load_voice(voice_name)
        if not voice_audio:
            return None, f"❌ Audio file missing for '{voice_name}'"

        progress(0.3, desc="Generating new segment...")
        new_path, gen_log = run_f5tts(text, voice_audio, voice_text, output_name="replacement.wav")
        if not new_path or not os.path.exists(new_path):
            return None, f"❌ Generation failed: {gen_log}"

        new_seg = AudioSegment.from_file(new_path)
        final = audio[:start_ms] + new_seg + audio[end_ms:]

        out = os.path.join(BASE_DIR, "edited_audio.wav")
        final.export(out, format="wav")
        return out, f"✅ Replaced {start_s}s to {end_s}s with new generated audio."
    except Exception as e:
        return None, f"❌ Error: {e}"

# ═══════════════════════════════════════════════════════════════════════
#  ML FEATURE: Audio Dataset Preprocessing (Task 3: noise + silence filters)
# ═══════════════════════════════════════════════════════════════════════
TRAINING_DIR = os.path.join(BASE_DIR, "training_data")
os.makedirs(TRAINING_DIR, exist_ok=True)


def _next_session_dir():
    """Return a fresh, non-colliding session_N directory."""
    i = 0
    while True:
        candidate = os.path.join(TRAINING_DIR, f"session_{i}")
        if not os.path.exists(candidate):
            os.makedirs(candidate)
            return candidate
        i += 1


def _reduce_noise(audio):
    """
    Spectral noise gate (Task 3: 'The Noise Filter').
    Removes background static/hum/music bleed so the AI trains on clean speech.
    Returns (audio, applied, message).
    """
    try:
        import numpy as np
        import noisereduce as nr
        # noisereduce works on a float signal; keep it 16-bit mono for safety.
        audio = audio.set_channels(1).set_sample_width(2)
        samples = np.array(audio.get_array_of_samples()).astype(np.float32)
        if samples.size == 0:
            return audio, False, "empty audio"
        reduced = nr.reduce_noise(y=samples, sr=audio.frame_rate,
                                  stationary=False, prop_decrease=0.85)
        cleaned = AudioSegment(
            np.clip(reduced, -32768, 32767).astype(np.int16).tobytes(),
            frame_rate=audio.frame_rate, sample_width=2, channels=1,
        )
        return cleaned, True, "noisereduce spectral gate"
    except ImportError:
        return audio, False, "noisereduce not installed — skipped"
    except Exception as e:
        return audio, False, f"noise reduction skipped ({e})"


def _remove_silence(audio, silence_thresh_db=-40, min_silence_len=400, keep_silence=150):
    """
    Silence cutter (Task 3: 'The Silence Cutter').
    Detects and removes 'dead air' so the model never trains on nothing,
    keeping a small pad around speech so cuts stay natural. Returns (audio, removed_ms).
    """
    try:
        from pydub.silence import detect_nonsilent
        ranges = detect_nonsilent(
            audio, min_silence_len=int(min_silence_len),
            silence_thresh=float(silence_thresh_db), seek_step=10,
        )
        if not ranges:
            return audio, 0  # nothing detected as speech — leave audio untouched
        out = AudioSegment.empty()
        for start, end in ranges:
            s = max(0, start - keep_silence)
            e = min(len(audio), end + keep_silence)
            out += audio[s:e]
        return out, max(0, len(audio) - len(out))
    except Exception:
        # If detection fails for any reason, don't crash the pipeline.
        return audio, 0


def preprocess_training_audio(audio_path, chunk_seconds=10, normalize_db=-20.0,
                              enable_denoise=True, silence_thresh_db=-40,
                              progress=gr.Progress()):
    """Real ML data pipeline: clean → normalize → de-silence → chunk for model training."""
    if not audio_path:
        return None, "Upload an audio file first."
    try:
        progress(0.1, desc="Loading raw audio...")
        audio = AudioSegment.from_file(audio_path)
        original_duration = len(audio) / 1000.0

        # Standardize early: mono + 16kHz (the standard for speech ML models).
        audio = audio.set_channels(1).set_frame_rate(16000)

        # Step 1: Noise Filter — strip background static/music before anything else.
        denoise_msg = "disabled"
        if enable_denoise:
            progress(0.3, desc="Filtering background noise...")
            audio, applied, denoise_msg = _reduce_noise(audio)
            if not applied:
                denoise_msg = f"⚠️ {denoise_msg}"

        # Step 2: Silence Cutter — remove dead air so we don't train on nothing.
        progress(0.5, desc="Cutting silent dead air...")
        audio, removed_ms = _remove_silence(audio, silence_thresh_db=silence_thresh_db)

        # Step 3: Normalize volume (consistent loudness across all chunks).
        progress(0.6, desc="Normalizing volume levels...")
        if audio.dBFS != float("-inf"):
            audio = audio.apply_gain(normalize_db - audio.dBFS)

        # Step 4: Chunk into training segments (drop stubs < 2s).
        progress(0.75, desc="Chunking into training segments...")
        chunk_ms = int(chunk_seconds * 1000)
        chunks = [audio[i:i + chunk_ms] for i in range(0, len(audio), chunk_ms)]
        chunks = [c for c in chunks if len(c) >= 2000]

        # Step 5: Export
        session_dir = _next_session_dir()
        progress(0.9, desc="Exporting clean training chunks...")
        for i, chunk in enumerate(chunks):
            chunk.export(os.path.join(session_dir, f"chunk_{i:03d}.wav"), format="wav")

        cleaned_duration = len(audio) / 1000.0
        log = (
            f"✅ Audio Dataset Preprocessed!\n"
            f"📊 Original Duration: {original_duration:.1f}s\n"
            f"🧹 Noise Filter: {denoise_msg}\n"
            f"🤫 Silence Removed: {removed_ms/1000.0:.1f}s of dead air "
            f"(threshold {silence_thresh_db} dBFS)\n"
            f"🔊 Normalized to: {normalize_db} dBFS\n"
            f"🎵 Resampled to: 16kHz Mono\n"
            f"⏱️ Clean Speech Duration: {cleaned_duration:.1f}s\n"
            f"✂️ Created {len(chunks)} training chunks ({chunk_seconds}s each)\n"
            f"📁 Saved to: {session_dir}"
        )
        if not chunks:
            log += (
                "\n\n⚠️ No usable chunks produced. The audio may be too short, "
                "entirely silent, or the silence threshold is too aggressive — "
                "try raising it toward -50 dBFS."
            )
        progress(1.0)
        return (session_dir if chunks else None), log
    except Exception as e:
        return None, f"❌ Preprocessing Error: {e}"

def analyze_voice_similarity(audio_a, audio_b, progress=gr.Progress()):
    """Real ML: Compare two audio files using Whisper encoder embeddings + cosine similarity."""
    if not audio_a or not audio_b:
        return "Upload both audio files to compare."
    try:
        progress(0.2, desc="Loading Whisper encoder...")
        import torch
        import numpy as np
        from transformers import WhisperProcessor, WhisperModel

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        processor = WhisperProcessor.from_pretrained("openai/whisper-base")
        model = WhisperModel.from_pretrained("openai/whisper-base").to(device).to(dtype)

        def get_embedding(path):
            audio = AudioSegment.from_file(path).set_channels(1).set_frame_rate(16000)
            if len(audio) > 15000:
                audio = audio[:15000]
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
            inputs = processor(samples, sampling_rate=16000, return_tensors="pt")
            input_features = inputs.input_features.to(device).to(dtype)
            with torch.no_grad():
                encoder_out = model.encoder(input_features)
                embedding = encoder_out.last_hidden_state.mean(dim=1).squeeze()
            return embedding

        progress(0.5, desc="Extracting voice embeddings...")
        emb_a = get_embedding(audio_a)
        progress(0.7, desc="Comparing voice signatures...")
        emb_b = get_embedding(audio_b)

        # Cosine Similarity
        cos_sim = torch.nn.functional.cosine_similarity(emb_a.unsqueeze(0), emb_b.unsqueeze(0)).item()
        similarity_pct = max(0, min(100, cos_sim * 100))

        # Cleanup GPU
        del model, processor, emb_a, emb_b
        import gc; gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        grade = "🟢 Excellent" if similarity_pct > 85 else "🟡 Good" if similarity_pct > 70 else "🔴 Poor"
        progress(1.0)
        return (
            f"🧠 Voice Similarity Analysis\n"
            f"{'='*40}\n"
            f"Cosine Similarity Score: {similarity_pct:.1f}%\n"
            f"Quality Grade: {grade}\n\n"
            f"{'='*40}\n"
            f"If the score is below 70%, consider:\n"
            f"  • Using a longer/cleaner reference audio\n"
            f"  • Fine-tuning the model with more training data\n"
            f"  • Adjusting the pitch shift parameter"
        )
    except Exception as e:
        return f"❌ Analysis Error: {e}"

# ═══════════════════════════════════════
#  GRADIO UI
# ═══════════════════════════════════════
import base64
# Logo lives in assets/ (kept root fallback for backwards compatibility).
logo_b64 = ""
for _candidate in (os.path.join(BASE_DIR, "assets", "LOGO.jpg"),
                   os.path.join(BASE_DIR, "LOGO.jpg")):
    if os.path.exists(_candidate):
        with open(_candidate, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode("utf-8")
        break

custom_css = """
footer {display: none !important;}
.zenvyro-header {text-align: center; padding: 20px 0; border-bottom: 2px solid #eee; margin-bottom: 20px;}
.zenvyro-logo {font-size: 2.5em; font-weight: 800; color: #2563eb; letter-spacing: 2px;}
.zenvyro-subtitle {font-size: 1.1em; color: #64748b; margin-top: 5px;}
"""

_logo_img = (f'<img src="data:image/jpeg;base64,{logo_b64}" alt="Zenvyrolabs Logo" '
             f'style="height: 80px; margin-bottom: 10px; display: inline-block;">') if logo_b64 else ""
header_html = f"""
    <div class="zenvyro-header">
        {_logo_img}
        <div class="zenvyro-logo">ZENVYROLABS</div>
        <div class="zenvyro-subtitle">Internal Advanced Voice Studio • Clone anime voices • Dramatic storytelling • Multi-voice podcasts</div>
    </div>
"""

with gr.Blocks(title="🎙️ Zenvyrolabs Voice Studio") as interface:
    gr.HTML(header_html)

    with gr.Tabs():
        # ─── TAB 1: Voice Cloner ───
        with gr.TabItem("🎭 Voice Cloner"):
            gr.Markdown("Upload any voice clip → the AI clones it and speaks your text in that voice.")
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📂 Voice Library")
                    saved_dd = gr.Dropdown(choices=get_saved_voices(), label="Saved Voices", interactive=True)
                    with gr.Row():
                        load_btn = gr.Button("📂 Load", size="sm")
                        del_btn = gr.Button("🗑️ Delete", size="sm", variant="stop")
                    gr.Markdown("---")
                    gr.Markdown("### 💾 Save Voice")
                    voice_name = gr.Textbox(label="Name", placeholder="e.g. Gojo_Dramatic")
                    save_btn = gr.Button("💾 Save to Library", variant="primary")
                    lib_status = gr.Textbox(label="Status", interactive=False)

                with gr.Column(scale=2):
                    gen_text1 = gr.Textbox(label="Script to Speak", lines=6, placeholder="Type your story here...")
                    ref_audio1 = gr.Audio(type="filepath", label="Reference Voice (auto-trims to 8s)")
                    with gr.Row():
                        ref_text1 = gr.Textbox(label="Reference Text", lines=2, scale=4,
                            placeholder="Type exact words from the reference audio...")
                        extract_btn1 = gr.Button("🔍 Auto-Extract", variant="secondary", scale=1)
                    clone_btn1 = gr.Button("🎙️ Generate Clone", variant="primary", size="lg")

            with gr.Row():
                out_audio1 = gr.Audio(label="Generated Audio")
                out_log1 = gr.Textbox(label="Log")

            load_btn.click(fn=load_voice, inputs=[saved_dd], outputs=[ref_audio1, ref_text1])
            extract_btn1.click(fn=extract_text_fn, inputs=[ref_audio1], outputs=[ref_text1])
            clone_btn1.click(fn=clone_voice_tab1, inputs=[gen_text1, ref_text1, ref_audio1], outputs=[out_audio1, out_log1])

        # ─── TAB 2: Dramatic Story Mode ───
        with gr.TabItem("🎬 Dramatic Story Mode", visible=False):
            gr.Markdown("""### How it works:
1. **Step 1:** Microsoft Neural AI creates a dramatic, emotional narration (perfect pronunciation & emotions).
2. **Step 2:** F5-TTS re-generates the same script using your saved anime voice (Gojo, Naruto, etc).
3. You get **two outputs** — pick whichever sounds better!

**Pro tip:** The emotion base alone sounds incredible for YouTube. The anime clone adds character flavor.""")

            with gr.Row():
                with gr.Column():
                    saved_dd2 = gr.Dropdown(choices=get_saved_voices(), label="Select Saved Anime Voice", interactive=True)
                    narrator_style = gr.Dropdown(
                        choices=list(NARRATOR_VOICES.keys()),
                        label="Emotion Narrator Style", value="Guy (Passionate Male)"
                    )
                    story_text = gr.Textbox(label="Your Story Script", lines=10,
                        placeholder="My daughter went missing five years ago...")
                    dramatic_btn = gr.Button("🎬 Generate Dramatic Voiceover", variant="primary", size="lg")

                with gr.Column():
                    gr.Markdown("### Step 1: Emotional Narration (Microsoft Neural)")
                    emotion_audio = gr.Audio(label="Emotion Base")
                    gr.Markdown("### Step 2: Anime Voice Clone (F5-TTS)")
                    clone_audio = gr.Audio(label="Anime Voice Version")
                    dramatic_log = gr.Textbox(label="Generation Log")

            dramatic_btn.click(fn=dramatic_clone,
                inputs=[story_text, saved_dd2, narrator_style],
                outputs=[emotion_audio, clone_audio, dramatic_log])

        # ─── TAB 3: Multi-Voice Podcast ───
        with gr.TabItem("🎙️ Multi-Voice Podcast"):
            gr.Markdown("""### Create Podcasts with Multiple Anime Voices
Write a script with character names that **match your saved voices**. Each line is generated with the correct voice and stitched into one seamless audio.

**Script Format:**
```
NARUTO: Hey Luffy, what's up man!
LUFFY: Yo Naruto! Just finished eating, I'm pumped!
NARUTO: Wanna go train together?
LUFFY: Let's gooo!
```
✅ Spacing around the colon is forgiven (`NARUTO :`, `NARUTO:`), names may contain spaces (`Iron Man`), and unknown characters get a **polite warning** instead of a crash.
🌏 Hindi/Urdu lines are auto-routed through **Microsoft Neural** for perfect pronunciation, then cloned into the character.""")

            with gr.Row():
                with gr.Column():
                    podcast_voices_dd = gr.Dropdown(choices=get_saved_voices(), multiselect=True, label="Your Saved Voices", info="Select the characters you want to use in your podcast script", interactive=True)
                    podcast_script = gr.Textbox(label="Podcast Script", lines=14,
                        placeholder="NARUTO: Hey Luffy, what's going on?\nLUFFY: Hey Naruto! Just had the best meat ever!\nNARUTO: That sounds awesome, want to spar?\nLUFFY: You're on!")
                    with gr.Row():
                        podcast_lang = gr.Radio(
                            ["Auto", "English", "Hindi/Urdu"], value="Auto",
                            label="Language Routing",
                            info="Auto detects Hindi/Urdu per line and uses Microsoft Neural for perfect pronunciation")
                        podcast_hindi_voice = gr.Dropdown(
                            choices=HINDI_URDU_VOICES, value="hi-IN-MadhurNeural",
                            label="Hindi/Urdu Neural Voice",
                            info="Base pronunciation voice for Hindi/Urdu lines")
                    pause_slider = gr.Slider(0, 2000, value=400, step=50,
                        label="Pause Between Lines (ms)", info="How long to pause between each character's line")
                    podcast_btn = gr.Button("🎙️ Generate Full Podcast", variant="primary", size="lg")

                with gr.Column():
                    podcast_audio = gr.Audio(label="Final Podcast Audio")
                    podcast_log = gr.Textbox(label="Generation Log", lines=15)

            podcast_btn.click(fn=generate_podcast,
                inputs=[podcast_script, pause_slider, podcast_lang, podcast_hindi_voice],
                outputs=[podcast_audio, podcast_log])

        # ─── TAB 4: Hindi / Urdu ───
        with gr.TabItem("🌏 Hindi / Urdu"):
            gr.Markdown("""### Perfect Hindi & Urdu Pronunciation
**Fix:** Auto-converts Roman Hindi/Urdu → Devanagari script before generating, so pronunciation is accurate.
- Type **Roman** (kya haal hai) → auto-converts to **Devanagari** (क्या हाल है)
- Or type directly in **Devanagari** for best quality""")

            with gr.Row():
                with gr.Column():
                    hindi_text = gr.Textbox(label="Hindi / Urdu Text", lines=6,
                        placeholder="Hello bhai, kya haal hai? Aaj hum ek bahut hi dilchasp kahani sunenge...")
                    transliterate_toggle = gr.Checkbox(label="🔄 Auto-convert Roman → Devanagari (Recommended!)", value=True)
                    hindi_voice = gr.Dropdown(
                        choices=HINDI_URDU_VOICES,
                        label="Voice", value="hi-IN-MadhurNeural",
                        info="Madhur=Hindi Male, Swara=Hindi Female, Asad=Urdu Male, Uzma=Urdu Female"
                    )
                    with gr.Row():
                        hindi_speed = gr.Slider(-30, 30, value=0, step=5, label="Speed (%)")
                        hindi_pitch = gr.Slider(-20, 20, value=0, step=2, label="Pitch (Hz)")
                    hindi_btn = gr.Button("🎙️ Generate Hindi/Urdu Voice", variant="primary", size="lg")

                with gr.Column():
                    hindi_audio = gr.Audio(label="Generated Audio")
                    hindi_log = gr.Textbox(label="Status")

            hindi_btn.click(fn=generate_hindi,
                inputs=[hindi_text, hindi_voice, transliterate_toggle, hindi_speed, hindi_pitch],
                outputs=[hindi_audio, hindi_log])

        # ─── TAB 5: Audio Editor ───
        with gr.TabItem("✂️ Audio Editor"):
            gr.Markdown("Upload an audio file (or download a generated one and upload here) to trim, cut, or completely replace a bad segment with a newly generated voice!")

            with gr.Row():
                with gr.Column(scale=1):
                    edit_audio_in = gr.Audio(type="filepath", label="Source Audio", interactive=True)
                    start_s = gr.Number(label="Start Time (seconds)", value=0.0)
                    end_s = gr.Number(label="End Time (seconds)", value=5.0)

                    with gr.Row():
                        trim_btn = gr.Button("✂️ Trim (Keep Only Selection)", variant="secondary")
                        cut_btn = gr.Button("🗑️ Cut (Remove Selection)", variant="secondary")

                    gr.Markdown("### Replace Segment")
                    replace_text = gr.Textbox(label="New Text for Segment", lines=2)
                    replace_voice = gr.Dropdown(choices=get_saved_voices(), label="Select Voice for New Segment", interactive=True)
                    replace_btn = gr.Button("🔄 Replace Segment", variant="primary")

                with gr.Column(scale=1):
                    edit_audio_out = gr.Audio(label="Edited Audio")
                    edit_log = gr.Textbox(label="Status Log")

            trim_btn.click(fn=edit_audio_trim, inputs=[edit_audio_in, start_s, end_s], outputs=[edit_audio_out, edit_log])
            cut_btn.click(fn=edit_audio_cut, inputs=[edit_audio_in, start_s, end_s], outputs=[edit_audio_out, edit_log])
            replace_btn.click(fn=edit_audio_replace, inputs=[edit_audio_in, start_s, end_s, replace_text, replace_voice], outputs=[edit_audio_out, edit_log])

        # ─── TAB 6: Voice-to-Voice (RVC) ───
        with gr.TabItem("🎤 Voice-to-Voice (RVC)", visible=False):
            gr.Markdown("""### True Emotional Voice Cloning (Speech-to-Speech)
Upload an audio of **you acting out a line**, select a downloaded `.pth` anime character model, and the AI will convert your voice while preserving exactly the timing, emotion, and breath.
*(Place your `.pth`/`.index` models in the `rvc_models/` folder.)*""")
            with gr.Row():
                with gr.Column():
                    rvc_in = gr.Audio(type="filepath", label="Input Audio (Your acting/reference)")
                    rvc_model = gr.Dropdown(choices=get_rvc_models(), label="RVC Model (.pth)", interactive=True)
                    rvc_refresh = gr.Button("🔄 Refresh Models List", size="sm")
                    rvc_pitch = gr.Slider(-24, 24, value=0, step=1, label="Pitch Shift (Semitones)", info="Use +12 for Male->Female, -12 for Female->Male. Leave 0 if same gender.")
                    rvc_btn = gr.Button("🎤 Convert Voice", variant="primary", size="lg")
                with gr.Column():
                    rvc_out = gr.Audio(label="Converted Audio")
                    rvc_log = gr.Textbox(label="Status Log", lines=10)

            rvc_btn.click(fn=run_rvc_conversion, inputs=[rvc_in, rvc_model, rvc_pitch], outputs=[rvc_out, rvc_log])
            rvc_refresh.click(fn=lambda: gr.update(choices=get_rvc_models()), outputs=[rvc_model])

        # ─── TAB 7: Perfect Pronunciation Clone ───
        with gr.TabItem("🌟 Perfect Pronunciation Clone", visible=False):
            gr.Markdown("""### Get Anime Voices with PERFECT Pronunciation
F5-TTS sometimes struggles with pronunciation. This tab fixes that!
It uses **Edge-TTS (Eric, Guy, etc.)** to generate perfect, native pronunciation, and then uses **RVC** to seamlessly morph that audio into your Anime character's voice.
*(Requires an RVC `.pth` model in `rvc_models/`)*""")
            with gr.Row():
                with gr.Column():
                    perf_text = gr.Textbox(label="Script", lines=6, placeholder="Type perfectly pronounced English here...")
                    perf_neural = gr.Dropdown(choices=list(NARRATOR_VOICES.keys()), label="Base Neural Voice (for acting/pronunciation)", value="Eric (Rational Male)")
                    perf_rvc = gr.Dropdown(choices=get_rvc_models(), label="Target Anime Voice (RVC Model)", interactive=True)
                    perf_pitch = gr.Slider(-24, 24, value=0, step=1, label="Pitch Shift", info="Match Neural gender to Anime gender. e.g. Male to Female: +12")
                    perf_btn = gr.Button("🌟 Generate Perfect Clone", variant="primary", size="lg")
                with gr.Column():
                    perf_audio = gr.Audio(label="Final Perfect Audio")
                    perf_log = gr.Textbox(label="Status Log")

            def run_perfect_clone(text, neural_voice, rvc_model, pitch, progress=gr.Progress()):
                if not text: return None, "Please enter text."
                if not rvc_model: return None, "Please select an RVC model."

                progress(0.2, desc="Generating perfect pronunciation...")
                voice_id = NARRATOR_VOICES.get(neural_voice, "en-US-EricNeural")
                temp_audio = os.path.join(TEMP_DIR, "perf_base.mp3")
                ok, err = run_edge_tts(text, voice_id, temp_audio)
                if not ok:
                    return None, f"❌ Edge-TTS failed: {err}"

                progress(0.6, desc="Morphing into Anime Voice (RVC)...")
                final_path, log = run_rvc_conversion(temp_audio, rvc_model, pitch)
                progress(1.0)
                return final_path, log

            perf_btn.click(fn=run_perfect_clone, inputs=[perf_text, perf_neural, perf_rvc, perf_pitch], outputs=[perf_audio, perf_log])

        # ─── TAB 8: Voice Training Studio (Real ML) ───
        with gr.TabItem("🧠 Voice Training Studio"):
            gr.Markdown("""### 🧠 AI Model Training Pipeline
This is the **core Machine Learning** feature of the application. Instead of relying on zero-shot cloning (which can sound robotic), you can **train a custom voice model** by feeding it high-quality audio data.

**How it works (Real ML Pipeline):**
1. **Upload** a long audio recording of your target voice (5-10 minutes recommended).
2. **Preprocess** — Our pipeline automatically **filters background noise/static**, **cuts silent dead air**, normalizes volume levels, resamples to 16kHz mono (the standard for speech ML models), and chunks the audio into clean 10-second training segments.
3. **Analyze** — Use the Voice Quality Analyzer to compare your cloned output vs the original and get a real ML similarity score using Whisper neural embeddings.

*This is the exact same data preprocessing pipeline used in production ML systems at companies like ElevenLabs and OpenAI.*""")

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Step 1: Upload Raw Training Audio")
                    train_audio = gr.Audio(type="filepath", label="Raw Training Audio (5-10 min recommended)")
                    chunk_size = gr.Slider(5, 30, value=10, step=1, label="Chunk Size (seconds)", info="Each chunk becomes one training sample")
                    norm_db = gr.Slider(-30, -10, value=-20, step=1, label="Target Volume (dBFS)", info="Normalizes all chunks to this volume level for consistent training")
                    denoise_toggle = gr.Checkbox(value=True, label="🧹 Noise Filter (remove background static/music)")
                    silence_slider = gr.Slider(-60, -20, value=-40, step=1, label="Silence Threshold (dBFS)",
                        info="Audio quieter than this is treated as 'dead air' and cut. Lower = cut only near-silence.")
                    preprocess_btn = gr.Button("⚙️ Preprocess Dataset", variant="primary", size="lg")

                with gr.Column():
                    gr.Markdown("### Preprocessing Results")
                    train_output_dir = gr.Textbox(label="Output Directory", interactive=False)
                    train_log = gr.Textbox(label="Pipeline Log", lines=12)

            preprocess_btn.click(fn=preprocess_training_audio,
                inputs=[train_audio, chunk_size, norm_db, denoise_toggle, silence_slider],
                outputs=[train_output_dir, train_log])

            gr.Markdown("---")
            gr.Markdown("""### Step 2: Voice Quality Analyzer (Cosine Similarity)
Upload the **original voice** and your **cloned output** to measure how accurate the clone is using real ML metrics.
The system uses **OpenAI Whisper's neural encoder** to extract voice embeddings and computes **cosine similarity** — the same technique used in speaker verification systems.""")

            with gr.Row():
                with gr.Column():
                    sim_audio_a = gr.Audio(type="filepath", label="Audio A: Original Voice")
                    sim_audio_b = gr.Audio(type="filepath", label="Audio B: Cloned Voice")
                    sim_btn = gr.Button("🧠 Analyze Similarity", variant="primary", size="lg")
                with gr.Column():
                    sim_result = gr.Textbox(label="ML Analysis Results", lines=12)

            sim_btn.click(fn=analyze_voice_similarity,
                inputs=[sim_audio_a, sim_audio_b],
                outputs=[sim_result])

    # Global event bindings
    save_btn.click(fn=save_voice, inputs=[voice_name, ref_audio1, ref_text1], outputs=[lib_status, saved_dd, saved_dd2, podcast_voices_dd, replace_voice])
    del_btn.click(fn=delete_voice, inputs=[saved_dd], outputs=[lib_status, saved_dd, saved_dd2, podcast_voices_dd, replace_voice])

if __name__ == "__main__":
    print("Launching Advanced Voice Studio...")
    print(f"Saved Voices: {get_saved_voices()}")
    # Configurable so the same code serves local (127.0.0.1) and Docker (0.0.0.0).
    server_name = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    in_docker = os.environ.get("IN_DOCKER", "").lower() in ("1", "true", "yes")
    interface.queue()
    interface.launch(server_name=server_name, server_port=server_port,
                     inbrowser=not in_docker, css=custom_css)
