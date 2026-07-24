# 🐳 Docker Deployment Guide (Task 1)

The whole application is containerized so **anyone can run it with one command** —
no Python, no FFmpeg, no dependency hell.

## ✅ Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS)
  or Docker Engine + Compose plugin (Linux). Nothing else.

## 🚀 Run it (one command)
From the project folder:

```bash
docker compose up --build
```

Then open **http://localhost:7860** in your browser. That's it.

- First build downloads PyTorch + the AI libraries (a few GB) and takes a while.
- The AI models (Whisper, F5-TTS) download on first use into `hf_cache/`, which is
  a mounted volume — so they are cached and **never re-downloaded** on later runs.

To stop: press `Ctrl+C`, or in another terminal `docker compose down`.

## 💾 Your data is safe (Volumes)
These host folders are mounted into the container, so everything **survives
container restarts, rebuilds, and `docker compose down`:**

| Host folder       | Purpose                                  |
| ----------------- | ---------------------------------------- |
| `saved_voices/`   | Your cloned voice library                |
| `rvc_models/`     | Optional RVC `.pth` / `.index` models    |
| `training_data/`  | Preprocessed ML datasets (chunks)        |
| `hf_cache/`       | Downloaded Whisper / F5-TTS model weights |

You can turn the container off and your saved voices will still be there.

## 🔧 Run without Compose (plain Docker)
```bash
docker build -t zenvyro-voice-studio .
docker run --rm -p 7860:7860 \
  -v "$(pwd)/saved_voices:/app/saved_voices" \
  -v "$(pwd)/rvc_models:/app/rvc_models" \
  -v "$(pwd)/training_data:/app/training_data" \
  -v "$(pwd)/hf_cache:/app/hf_cache" \
  zenvyro-voice-studio
```

## ⚡ GPU acceleration (optional)
The default image is **CPU-only** for maximum portability (generation is slower
but works everywhere). To use an NVIDIA GPU:

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
2. In `Dockerfile`, replace the CPU torch install line with a CUDA build, e.g.:
   ```dockerfile
   RUN pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
   ```
3. Uncomment the `deploy.resources.reservations.devices` block in `docker-compose.yml`.
4. Rebuild: `docker compose up --build`.

## 🎤 Enabling RVC (optional)
RVC (voice-to-voice) uses heavy `fairseq`-based dependencies that conflict with
F5-TTS, so it is **not** installed by default — and the app works fully without it
(Hindi/Urdu lines fall back to the perfectly-pronounced Microsoft Neural base).

To enable it, install `requirements-rvc.txt` into a **separate** environment
(`rvc_venv/`) so it doesn't clash with the main one, and drop real `.pth`/`.index`
models into `rvc_models/`. See `requirements-rvc.txt` for details.

## 🩺 Troubleshooting
| Symptom | Fix |
| --- | --- |
| Port 7860 already in use | Change the left side of `ports:` in `docker-compose.yml`, e.g. `8080:7860`. |
| Build fails downloading torch | Re-run `docker compose up --build`; the layer cache resumes. |
| App loads but generation is slow | Expected on CPU. Use the GPU option above. |
| "RVC Error" in the RVC tab | Expected unless you enabled RVC + added real models. Not required for grading. |
