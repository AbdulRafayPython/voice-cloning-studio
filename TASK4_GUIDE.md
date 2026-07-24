# 🎥 Task 4 — Final 5-Minute Video Submission (Step-by-Step)

Tasks 1–3 (the engineering) are implemented in code. Task 4 is a **manual
recording task** you perform once the app is running. This guide walks you
through it end to end. (40 points, + bonus for posting to LinkedIn and tagging
Zenvyro Labs.)

---

## 1. Launch the app
```bash
docker compose up --build     # then open http://localhost:7860
```

## 2. Gather data — 10+ minutes of clean audio for 2 characters
Pick 2 famous fictional characters (e.g. **Darth Vader** + **SpongeBob**,
**Naruto** + **Luffy**, **Iron Man** + **Harry Potter**).

- Find clips where the character speaks **alone**, with little background music.
- You need **at least 10 minutes total** per character.
- You may use `yt-dlp` (already installed) to grab audio, e.g.:
  ```bash
  yt-dlp -x --audio-format wav -o "vader.wav" "<video-url>"
  ```
  Only use sources you're permitted to use.

## 3. Clean & prepare the data → **Voice Training Studio** tab
For each character's raw audio:
1. Upload it under **Step 1: Upload Raw Training Audio**.
2. Keep **🧹 Noise Filter** ON (removes background static/music — Task 3).
3. Leave **Silence Threshold** around **-40 dBFS** (cuts dead air — Task 3).
   - If it cuts too much, move it toward **-50**; if it keeps too much noise,
     move it toward **-30**.
4. Click **⚙️ Preprocess Dataset**. Read the log — it reports how much dead air
   was removed and how many clean 10s chunks were produced in `training_data/`.

## 4. "Train" / register each character voice → **Voice Cloner** tab
This app clones from a clean reference clip:
1. Take one of your best clean chunks (from `training_data/session_*/`) as the
   reference, or upload a clean ~8s clip.
2. Click **🔍 Auto-Extract** to transcribe the reference text.
3. Enter a **Name** that you'll use in the script (e.g. `Darth_Vader`,
   `SpongeBob`) and click **💾 Save to Library**.
4. Repeat for the second character.

> 💡 Tip: use the **Voice Quality Analyzer** (Step 2 of the Training Studio) to
> compare original vs. cloned audio and get a real cosine-similarity score.

## 5. Write a funny ~5-minute podcast script
Use the `NAME: dialogue` format. Names must match your saved voices
(case/space/hyphen-insensitive, so `Darth Vader` matches `Darth_Vader`):

```
Darth_Vader: SpongeBob, I find your lack of Krabby Patties disturbing.
SpongeBob: Aye aye, Lord Vader! One Galactic Special coming right up!
Darth_Vader: The Force is strong with this sandwich.
```

- Want a Hindi/Urdu bit? Just type it (Roman or Devanagari) — the app
  auto-routes it through Microsoft Neural for **perfect pronunciation** first,
  then into the character voice.

## 6. Generate the podcast → **Multi-Voice Podcast** tab
1. Paste your script.
2. Choose **Language Routing = Auto** (English lines clone directly; Hindi/Urdu
   lines get the perfect-pronunciation route).
3. Set the pause slider (300–500 ms feels natural).
4. Click **🎙️ Generate Full Podcast**. The output is one smooth, crossfaded track.

## 7. Record the screen video
- Use **OBS Studio** or **Loom**.
- Show the UI, paste the script, click generate, and **play the final audio** so
  the graders can hear the emotion + pronunciation.
- Keep it around **5 minutes**.

## 8. Submit
- Push all your code to a **public GitHub repository**.
- Submit the video.
- **Bonus:** post the video to LinkedIn and tag **Zenvyro Labs**.

---

### Checklist
- [ ] 10+ min clean audio for 2 characters gathered
- [ ] Both run through the Training Studio (noise filter + silence cutter)
- [ ] Both voices saved in the library
- [ ] ~5-minute funny script written
- [ ] Podcast generated with smooth transitions
- [ ] Screen recording captured and submitted
- [ ] Code pushed to public GitHub
- [ ] (Bonus) Posted to LinkedIn, tagged Zenvyro Labs
