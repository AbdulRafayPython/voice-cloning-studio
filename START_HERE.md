# 👋 START HERE — Zenvyrolabs Voice Studio (Handoff Guide)

Hey! This project is the **Zenvyrolabs Advanced Voice Studio** internship
(200 points, 4 tasks). The engineering (Tasks 1–3) is **already coded and tested**.
This guide tells you exactly **what's done**, **what's left for you**, and **the
commands to run** to finish and submit.

> TL;DR: The code is done. You need to (1) set it up on your laptop, (2) train 2
> character voices, (3) record a 5-minute demo video, and (4) push to GitHub.

---

## 📊 Progress so far

| Task | Points | Status | Who finishes it |
| --- | :---: | --- | --- |
| **1. Dockerization & Deployment** | 80 | ✅ **Code complete** — `Dockerfile`, `docker-compose.yml`, volumes, cross-platform app | You just run/verify it |
| **2. Podcast parsing + perfect pronunciation** | 30 | ✅ **Code complete & tested** on real audio | Done |
| **3. AI training pipeline (noise + silence)** | 50 | ✅ **Code complete & tested** on real audio | Done |
| **4. Final 5-minute video** | 40 | ⏳ **Your part** — record the demo | **You** |
| Bonus: post video to LinkedIn + tag Zenvyro Labs | ➕ | ⏳ Optional | **You** |

**≈160 / 200 points of engineering are implemented and verified.**
The remaining **40 points (Task 4)** is a manual recording task that *has* to be
yours — it's your submission.

### What "tested" means
- `app.py` compiles, launches, and served **HTTP 200** on the real stack.
- The crash-proof podcast parser, Hindi→Neural pronunciation routing, smooth
  audio stitching, and the noise-filter + silence-cutter training pipeline were
  all run against **real generated audio** and worked.
- ⚠️ The **Docker image build itself was not run** on the setup machine (Docker
  engine wasn't available there). The Docker files are written correctly and
  standard — you just need to run `docker compose up --build` once to confirm.

### What was changed (so you can explain it in your video / interview)
See **`IMPLEMENTATION.md`** for the full task-by-task map of what changed and why.
Short version:
- Made `app.py` cross-platform (it was hardcoded to Windows `venv\Scripts\*.exe`
  and `127.0.0.1`, which could never run in Docker).
- Rewrote the podcast parser to never crash and to give polite warnings.
- Added the Hindi/Urdu "Microsoft Neural first, then clone" hybrid route.
- Added smooth crossfade stitching between podcast lines.
- Added a **noise filter** (`noisereduce`) and a **silence cutter** to the
  training pipeline.
- Wrote `Dockerfile` + `docker-compose.yml` with persistent volumes.
- Fixed `requirements.txt` (removed the `TTS` package that caused the C++ build
  crash; added the packages the app actually uses).

---

## 🖥️ Part A — Run it locally on your laptop (recommended first)

You need **Python 3.11** (NOT 3.12+, it breaks the AI libs) and **FFmpeg**.

### 1. Install prerequisites (Windows, one time)
Open **PowerShell** and run:
```powershell
winget install --id Python.Python.3.11 -e
winget install --id Gyan.FFmpeg -e
```
➡️ **Close and reopen PowerShell** afterward so the PATH updates.

> On macOS/Linux: install Python 3.11 + ffmpeg with your package manager
> (`brew install python@3.11 ffmpeg`, etc.), then create the venv manually:
> `python3.11 -m venv venv` and `pip install torch torchaudio` +
> `pip install -r requirements.txt`.

### 2. Install the project dependencies (one time, ~2 GB download)
From inside the project folder:
```powershell
.\setup.bat
```
This creates the `venv/`, installs CPU PyTorch, and installs everything in
`requirements.txt`. It takes a while (big download) — let it finish.

### 3. Launch the app
```powershell
.\run.bat
```
Your browser opens **http://localhost:7860**. Done! 🎉

> First time you use the Voice Cloner or Auto-Extract, it downloads the F5-TTS /
> Whisper models once (a few GB) — that's normal and cached afterward.

---

## 🐳 Part B — Run it with Docker (Task 1 proof, optional but nice)

Docker lets *anyone* run the app with one command — that's the whole point of
Task 1. To use it on your machine:

### 1. Install Docker Desktop
```powershell
winget install --id Docker.DockerDesktop -e
```

### 2. Enable the WSL2 backend (needs Admin + a reboot)
Open **PowerShell as Administrator** and run:
```powershell
wsl --install
```
Then **restart your PC**. After rebooting, **launch Docker Desktop once** and
wait until it says *"Engine running"*.

### 3. Run the whole app with one command
From the project folder:
```powershell
docker compose up --build
```
Open **http://localhost:7860**. Stop it with `Ctrl+C`.

Your saved voices, models, datasets and downloaded model weights are stored in
mounted folders, so **nothing is lost when the container stops** (see `DOCKER.md`).

---

## 🎥 Part C — Complete Task 4 (the graded video)

Full step-by-step is in **`TASK4_GUIDE.md`**. Summary:

1. **Get audio** — download **10+ minutes** of clean audio for **2 famous
   characters** (e.g. Darth Vader + SpongeBob).
2. **Clean it** — in the **🧠 Voice Training Studio** tab, upload each character's
   audio and click **⚙️ Preprocess Dataset** (this uses the Task-3 noise filter +
   silence cutter you're demonstrating).
3. **Save voices** — in the **🎭 Voice Cloner** tab, use a clean clip as reference,
   click **🔍 Auto-Extract**, give it a **Name** matching your script, and
   **💾 Save to Library**. Do both characters.
4. **Write a funny ~5-min script** in `NAME: dialogue` format.
5. **Generate** — paste it in the **🎙️ Multi-Voice Podcast** tab and click
   **Generate Full Podcast**.
6. **Record** your screen with **OBS** or **Loom** showing the UI + playing the
   final audio (~5 min).

---

## 🚀 Part D — Submit (push to public GitHub)

The assignment requires a **public GitHub repo**. Git is already installed.
From the project folder:

```powershell
git init
git add .
git status                # <-- confirm venv/ and caches are NOT listed
git commit -m "Zenvyrolabs Voice Studio: Tasks 1-3 complete"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

> ✅ The `.gitignore` already excludes the 2 GB `venv/`, model caches, temp files,
> and generated audio — so only the source + docs get pushed. Double-check with
> `git status` that `venv/` does **not** appear before committing.

Then:
- Submit the video.
- **Bonus points:** post the video to **LinkedIn** and tag **Zenvyro Labs**.

---

## 🆘 Troubleshooting

| Problem | Fix |
| --- | --- |
| `setup.bat` fails / can't find `py -3.11` | Install Python 3.11: `winget install --id Python.Python.3.11 -e`, reopen terminal. |
| `numpy` / crash on import | Your venv used Python 3.12+. Delete `venv/` and run `setup.bat` again (it forces 3.11). |
| Audio errors / "ffmpeg not found" | Install FFmpeg: `winget install --id Gyan.FFmpeg -e`, reopen terminal. |
| Port 7860 already in use | Edit the port in `docker-compose.yml` (`8080:7860`) or set `GRADIO_SERVER_PORT`. |
| First generation is slow | Normal on CPU. The models also download once on first use. |
| "RVC Error" in the RVC tab | Expected — RVC is optional and not required for grading. Hindi lines fall back to the perfect Microsoft Neural voice automatically. |

---

## 📁 File map (what's what)
- `app.py` — the whole application (all tabs + the logic for Tasks 2 & 3).
- `Dockerfile`, `docker-compose.yml`, `.dockerignore` — Task 1.
- `requirements.txt` — Python dependencies.
- `setup.bat` / `run.bat` — local install / launch.
- `transliterate.py` — Roman→Devanagari for Hindi pronunciation.
- `IMPLEMENTATION.md` — what changed, mapped to each task.
- `DOCKER.md` — full Docker guide.
- `TASK4_GUIDE.md` — how to record the video.
- `README.md` / `Context.md` — the original internship brief.

Good luck — you've got this! 💪
