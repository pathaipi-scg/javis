# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two layers, different maturity:

- **`docs/`** — design docs (in Thai) for the *full planned system*: a meeting → knowledge-base pipeline on **Django + MSSQL + WhisperX + Django-Q2**. This system is **not built yet** — docs are the spec/blueprint (also feed Canva slides). Read `docs/README.md` first for the index.
- **`demo/`** — a **working FastAPI prototype** (server-renders the existing Jinja2 pages) that implements a slimmed-down slice of the pipeline end to end. This is the only runnable code. When asked to "run the app" or change behavior, this is almost always the target. A Vue SPA frontend is planned but not built yet — routes still return HTML, not JSON.

Do not assume the Django/MSSQL stack exists in code — it is the future target described in `docs/`, while `demo/` is the present reality (FastAPI + Jinja2, no DB, files written straight to an Obsidian vault).

## Pipeline (what the demo does)

Audio + image(+caption) → transcript (faster-whisper) + caption merged into one context → an LLM (currently **Typhoon2 8B**, a Thai-tuned Llama 3.1) extracts machine-maintenance data as JSON → render Markdown preview → on Save, write to an Obsidian vault.

`demo/app.py` wires it: `/process` runs transcribe → extract → render; `/save` writes to vault. Three modules behind it:
- `transcribe.py` — `transcribe_audio(path)` via faster-whisper (Thai, VAD).
- `llm.py` — `extract_machines(context, image_path)` → dict; `render_markdown(...)` → `.md` string.
- `vault.py` — `save_to_vault(markdown, machines, date)` writes `meetings/<date>.md` (overwrite) and `machines/machine-X.md` (create + append a history row).

## Graceful-degradation design (important)

`transcribe.py` and `llm.py` are built to **run without their backends**. If `faster-whisper` isn't installed, or the LLM server (Typhoon) is unreachable, each `except` returns **mock data** so the UI demos end to end. This is intentional — so a `[MOCK — ...]` prefix in output means the real backend was never reached, **not** that the code is broken. Check `.env` / server reachability before "fixing" mock output.

## Running

```bash
cd demo
copy .env.example .env   # then fill in real values (Windows)
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

`faster-whisper` is commented out in `requirements.txt` — install it separately (`pip install faster-whisper`) only when you want real transcription; otherwise the mock runs.

No test suite, linter, or build step exists. Verify changes by running `app.py` and exercising the form.

## Configuration (`demo/.env`)

All backends are configured via env (loaded by `python-dotenv`); `llm.py` header constants are the fallbacks.

> **Naming note:** the `QWEN_*` env vars are historical. The project started on **Qwen3-VL** but pivoted to **Typhoon2 8B** (a Thai-tuned Llama 3.1) for stronger Thai once image analysis was dropped. The vars still drive the OpenAI-compatible client regardless of which model/vendor is behind them — they were not renamed to avoid touching code.

- `QWEN_BASE_URL` — OpenAI-compatible base. Point it at wherever the model is served: `127.0.0.1:11434/v1` if Ollama runs on the **same** machine, or the server's **real IP** if it runs on a separate box (never `127.0.0.1` in that case). URL is auto-normalized to end in `/v1`. Ollama `:11434/v1`, vLLM `:8000/v1`, AnythingLLM `:3001/api/v1/openai`.
- `QWEN_MODEL` — the served model. **Currently `scb10x/llama3.1-typhoon2-8b-instruct`** (Typhoon2 8B). Was `qwen3-vl:4b` before the pivot.
- `QWEN_VISION` — `1` sends the image into the LLM directly (only for VL models). **Currently `0`** — Typhoon is text-only, so the image is *not* analyzed; only its caption text feeds the context. Set back to `1` only with a VL model.
- `QWEN_API_KEY` — usually `not-needed` for local servers.
- `WHISPER_MODEL` / `WHISPER_DEVICE` — `cuda` if a GPU is available, else `cpu` (slow).
- `VAULT_PATH` — existing Obsidian vault root; `meetings/` and `machines/` subfolders are created under it.

`.env` and `demo/.env` are gitignored.

## Conventions

- Code comments, docstrings, prompts, and UI strings are in **Thai** — match that when editing.
- The LLM is reached through the **OpenAI-compatible** API only (vLLM / Ollama / LM Studio are interchangeable — change just URL + model name; never hardcode a vendor SDK).
- MSSQL is described in docs as the intended source of truth with `.md` as a regenerable view; the demo skips the DB and writes `.md` directly.