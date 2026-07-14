# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Three layers, different maturity:

- **`docs/`** — design docs (in Thai) for the *full planned system*: a meeting → knowledge-base pipeline on **Django + MSSQL + WhisperX + Django-Q2**. This system is **not built yet** — docs are the spec/blueprint (also feed Canva slides). Read `docs/README.md` first for the index.
- **`backend/`** — the **working FastAPI backend**: JSON API only, all under `/api/*` (`ask` RAG, `models`, `plants`, `form-options`, `cases/preview`, `cases/save`, `case/{case_id}` (single-case detail for the citation sidebar), `search`, `dashboard`, `bubbles`, `graph`, `stt`, `stt-config`, `transcribe`, `tts`, `tts-stream`, `history`). Serves the built React SPA at `/` from `frontend/dist` (if not built yet, `/` shows a build hint; `/api/*` still works). The old Jinja2 HTML pages were **removed** — the UI is 100% React now. (Folder was renamed from `demo/` — older commits may still say `demo`; the leftover `demo/` copy has been deleted.)
- **`frontend/`** — **React 18 + Vite 5 SPA** (dark "Jarvis" theme, hash routing: `#/` landing (main voice HUD), `#/case`, `#/search`, `#/stt`, `#/dashboard` (bubble dashboard), `#/graph`, `#/stats`). Dev: `npm run dev` on :5173 (proxies `/api` → :5000). Production: `npm run build` → `dist/` served by FastAPI at :5000 — single app, single port. (The old `#/ask` page `AskDemo.jsx` was **retired** — folded into Landing; `#/ask` now redirects home.) **Voice:** wake word "hey jarvis" runs **fully in-browser** via openWakeWord (onnxruntime WASM, `frontend/src/voice/oww.js`) — no audio leaves the browser; plus push-to-talk. Voice commands navigate (`matchNav` in `voice/nav.js`), and `VoiceNav.jsx` floats a mic on non-home pages.

Do not assume the Django/MSSQL stack exists in code — it is the future target described in `docs/`, while `backend/` + `frontend/` are the present reality (FastAPI + React, no DB, files written straight to an Obsidian vault).

## Pipeline (what the backend does)

Audio + image(+caption) → transcript + caption merged into one context → an LLM extracts machine-maintenance data as JSON → render Markdown preview → on Save, write to an Obsidian vault. Separately, `/api/ask` answers questions via RAG over the vault.

**LLM is multi-provider now** (the React UI has a model picker; `/api/models` lists them, request body `model` selects one). Lanes: **Azure OpenAI `gpt-5.4-mini`** (the app's default when configured), local **Typhoon2 8B** (Thai-tuned Llama 3.1, via the `QWEN_*` OpenAI-compatible client), and an **n8n webhook proxy** lane. All reached over the OpenAI-compatible API — no vendor SDK hardcoded.

`backend/app.py` wires it via the `/api/*` endpoints (the React SPA calls them). Modules behind it:
- `transcribe.py` — `transcribe_audio(path)`; engine `STT_ENGINE` = openai (`gpt-4o-transcribe`) | gemini | whisper (faster-whisper, Thai/VAD).
- `tts.py` — `synthesize(text)` + `stream_openai(text)` (streaming); engine `TTS_ENGINE` = openai (`gpt-4o-mini-tts`, voice `verse`) | gemini | windows. Shared OpenAI/Azure audio client in `openai_audio.py`.
- `llm.py` — `extract_machines(context, image_path)` → dict; `render_markdown(...)` → `.md` string.
- `rag.py` — the `/api/ask` brain: bge-m3 embeddings + cross-encoder rerank over the vault, then an LLM lane (Azure GPT / Typhoon / n8n) summarizes with `case_id` citations. Also powers `bubbles`/`graph`.
- `vault.py` — `save_to_vault(markdown, machines, date)` writes `meetings/<date>.md` (overwrite) and `machines/machine-X.md` (create + append a history row).

## Graceful-degradation design (important)

`transcribe.py`, `llm.py`, and `rag.py` are built to **run without their backends**. If `faster-whisper` isn't installed, or the LLM lane (Azure/Typhoon/n8n) is unreachable, each `except` returns **mock data** so the UI demos end to end. This is intentional — so a `[MOCK — ...]` prefix in output means the real backend was never reached, **not** that the code is broken. Check `.env` / server reachability before "fixing" mock output.

## Running

Normal use — one command (FastAPI serves the built React app):
```bash
cd backend
copy .env.example .env   # then fill in real values (Windows)
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```
A local venv already exists at `backend/.venv` (Python 3.12, faster-whisper + CUDA installed). Invoke it directly without activating: `.\.venv\Scripts\python.exe app.py`.

Editing the UI (live reload): also run `cd frontend && npm run dev` (:5173, proxies `/api` → :5000). **After changing frontend code you must `npm run build`** for :5000 to reflect it — the dev server auto-reloads, the built `dist/` does not.

`faster-whisper` is commented out in `requirements.txt` — install it separately (`pip install faster-whisper`) only when you want real transcription; otherwise the mock runs.

No test suite or linter exists. Verify changes by running `app.py` and exercising the React UI (or hitting `/api/*` directly).

## Configuration (`backend/.env`)

All backends are configured via env (loaded by `python-dotenv`); `llm.py` header constants are the fallbacks.

> **Naming note:** the `QWEN_*` env vars are historical. The project started on **Qwen3-VL** but pivoted to **Typhoon2 8B** (a Thai-tuned Llama 3.1) for stronger Thai once image analysis was dropped. The vars still drive the OpenAI-compatible **local** lane regardless of which model/vendor is behind them — they were not renamed to avoid touching code. The cloud default is now Azure GPT (below), not Typhoon.

Local LLM lane (Typhoon / Ollama / vLLM):
- `QWEN_BASE_URL` — OpenAI-compatible base. Point it at wherever the model is served: `127.0.0.1:11434/v1` if Ollama runs on the **same** machine, or the server's **real IP** if on a separate box (never `127.0.0.1` in that case). Auto-normalized to end in `/v1`. Ollama `:11434/v1`, vLLM `:8000/v1`, AnythingLLM `:3001/api/v1/openai`.
- `QWEN_MODEL` — the served model. Currently `scb10x/llama3.1-typhoon2-8b-instruct` (Typhoon2 8B).
- `QWEN_VISION` — `1` sends the image into the LLM (VL models only). **Currently `0`** — Typhoon is text-only; only the caption text feeds the context.
- `QWEN_API_KEY` — usually `not-needed` for local servers.

Cloud LLM lane (default when set):
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_API_VERSION` / `AZURE_OPENAI_DEPLOYMENT` — Azure OpenAI (`gpt-5.4-mini`). When present, the React model picker defaults to it. Optional `N8N_ASK_URL` routes `/api/ask` through an n8n webhook instead of calling Azure directly (keeps the key off the app box).

RAG / embeddings:
- `EMBED_MODEL` — retrieval/RAG embeddings, `bge-m3` on the same Ollama. Optional `RAG_RERANK_MODEL` — CPU cross-encoder reranker.

Audio (TTS/STT — OpenAI/Azure by default):
- `STT_ENGINE` = `openai` | `gemini` | `whisper`; `TTS_ENGINE` = `openai` | `gemini` | `windows`.
- `OPENAI_AUDIO_ENDPOINT` / `OPENAI_AUDIO_API_KEY`, `OPENAI_STT_DEPLOYMENT` (`gpt-4o-transcribe`), `OPENAI_TTS_DEPLOYMENT` (`gpt-4o-mini-tts`), `OPENAI_TTS_VOICE` (`verse`). `GEMINI_API_KEY` + `GEMINI_STT_MODEL` / `GEMINI_TTS_VOICE` for the Gemini lane.
- `WHISPER_MODEL` / `WHISPER_DEVICE` — `cuda` if a GPU is available, else `cpu` (slow) — only used when `STT_ENGINE=whisper`.
- `VAULT_PATH` — existing Obsidian vault root; `meetings/` and `machines/` subfolders are created under it.

`.env` and `backend/.env` are gitignored.

## Conventions

- Code comments, docstrings, prompts, and UI strings are in **Thai** — match that when editing.
- The LLM is reached through the **OpenAI-compatible** API only (vLLM / Ollama / LM Studio are interchangeable — change just URL + model name; never hardcode a vendor SDK).
- MSSQL is described in docs as the intended source of truth with `.md` as a regenerable view; the backend skips the DB and writes `.md` directly.