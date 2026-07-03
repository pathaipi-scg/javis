# GUIDE — คู่มือฉบับเข้าใจง่าย

คู่มือสรุปว่าโปรเจกต์นี้มีไฟล์อะไรสำคัญบ้าง แต่ละไฟล์ทำอะไร และระบบทำงานยังไงตั้งแต่ต้นจนจบ
เขียนแบบง่าย เหมาะเป็นจุดเริ่มก่อนอ่านโค้ดจริง (รายละเอียดเชิงลึกอยู่ใน `CLAUDE.md` + `docs/`)

---

## 1. ภาพรวม 30 วินาที

Jarvis = ผู้ช่วยความรู้ซ่อมบำรุงเครื่องจักร ทำ 2 อย่างหลัก:

1. **บันทึกเคส** — พูด/อัดเสียง → ถอดเป็นข้อความ → ดึงข้อมูลเครื่องจักร → เซฟเป็นไฟล์ `.md`
2. **ถาม-ตอบ (RAG)** — ถามเป็นภาษาไทย → ค้นเคสที่เกี่ยว → ตอบพร้อมอ้างอิงเคส

**1 แอพ 1 พอร์ต (:5000):** FastAPI เสิร์ฟทั้ง API (`/api/*`) และหน้าเว็บ React (`/`)

```
เสียง/คำถาม → [เบราว์เซอร์ React] → [FastAPI :5000] → [Whisper / Typhoon / bge-m3] → ไฟล์ .md ใน vault
```

---

## 2. 3 โมเดล AI (จำแยกให้ชัด — คนละงาน)

| โมเดล | หน้าที่ | รันที่ไหน |
|-------|---------|-----------|
| **Whisper** (faster-whisper) | เสียง → ข้อความ (ถอดเสียง) | ในโปรเซส Python เอง (GPU) |
| **Typhoon2 8B** (Llama ไทย) | ดึงข้อมูลเครื่องจักร + ตอบคำถาม | Ollama (:11434) |
| **bge-m3** | ค้นหา: แปลงข้อความเป็นเวกเตอร์ (embedding) | Ollama (:11434) |

> ⚠️ **Whisper ไม่ได้อยู่ใน Ollama** — มันเป็น library ในโค้ด Python. มีแค่ Typhoon + bge ที่อยู่ใน Ollama
> ทั้ง 3 ตัวแชร์ GPU 12GB ใบเดียวกัน (รวม ~11GB — ตึง)

---

## 3. ไฟล์สำคัญ — Backend (`backend/`)

FastAPI + Python. ไม่มี DB เขียนไฟล์ `.md` ตรงลง Obsidian vault

### `app.py` — ตัวหลัก เชื่อมทุกอย่าง
เว็บเซิร์ฟเวอร์ (FastAPI). ทำ 2 หน้าที่:
- **API** ทุกเส้นขึ้น `/api/*` → คืน JSON (`ask`, `search`, `transcribe`, `stt`, `dashboard`, ...)
- **เสิร์ฟหน้าเว็บ** ที่ `/` → ส่งไฟล์ React ที่ build แล้วจาก `frontend/dist`

```python
@app.post("/api/ask")        # ถาม → เรียก rag.answer → คืนคำตอบ
@app.post("/api/transcribe") # เสียง → เรียก transcribe_audio → คืนข้อความ
@app.get("/")                # ส่งหน้าเว็บ React
```

### `transcribe.py` — ถอดเสียง (Whisper)
`transcribe_audio(path)` → เสียง → ข้อความไทย
- โหลดโมเดลครั้งเดียว cache ไว้ (`_get_model`) — เร็วขึ้น 5×
- `initial_prompt` = ใบ้ศัพท์ซ่อมบำรุงให้ถอดแม่นขึ้น
- ต่อ Whisper ไม่ได้ → คืน mock (ไม่ error)

### `rag.py` — ค้นหา + ถาม-ตอบ (bge-m3 + Typhoon)
หัวใจของ RAG. 2 ฟังก์ชันหลัก:
- `search(query, plant)` — bge-m3 แปลงเป็นเวกเตอร์ → cosine similarity → คืนเคสที่เกี่ยว
- `answer(query, plant)` — เอาเคสที่ค้นได้ → ให้ Typhoon เรียบเรียงตอบ + อ้าง case_id

```
คำถาม → bge-m3 หาเคสเกี่ยว (k อัน) → Typhoon อ่านแล้วตอบ → {text, citations}
```

### `llm.py` — ดึงข้อมูลเครื่องจักร (Typhoon)
`extract_machines(context)` → ข้อความประชุม → dict เครื่องจักร (machine/อาการ/วิธีแก้)
`render_markdown(...)` → dict → ข้อความ `.md`
> "extract" ไม่ใช่ "สรุป" — ดึงเป็น field มีโครงสร้าง ค้นต่อได้

### `vault.py` — เขียนไฟล์ลง Obsidian
`save_case(fields)` / `save_markdown(md)` → เขียนไฟล์ `cases/MTN-YYYY-NNNN.md`
สร้าง case_id อัตโนมัติ (ไม่ซ้ำ)

### `tts.py` — ข้อความ → เสียง (อ่านคำตอบ)
edge-tts อ่านคำตอบเป็นเสียงไทย (fallback เป็นเสียงเบราว์เซอร์)

---

## 4. ไฟล์สำคัญ — Frontend (`frontend/src/`)

React 18 + Vite. หน้าเดียว (SPA) เปลี่ยนหน้าด้วย hash (`#/ask`, `#/search`)

### `App.jsx` — router + โครงหน้า
อ่าน `#/...` จาก URL → ตัดสินว่าโชว์หน้าไหน (ไม่ต้องโหลดใหม่จาก server)
```js
if (hash.startsWith('#/search')) return 'search'   // → วาด <SearchPage />
```

### `components/` — แต่ละหน้า
| ไฟล์ | หน้า | ทำอะไร |
|------|------|--------|
| `Hero.jsx` + `Features.jsx` | `#/` | landing |
| `AskDemo.jsx` | `#/ask` | ถาม RAG + อัดเสียงถาม (ไมค์) + ฟังคำตอบ |
| `CasePage.jsx` | `#/case` | ป้อนเคสซ่อมบำรุง |
| `SearchPage.jsx` | `#/search` | ค้นเคส |
| `SttPage.jsx` | `#/stt` | อัปคลิป ทดสอบความแม่น Whisper |
| `DashboardPage.jsx` | `#/dashboard` | สรุปตัวเลข |
| `Navbar.jsx` / `Footer.jsx` | ทุกหน้า | เมนู (`<a href="#/...">`) |

> React ยิง `/api/*` ไปเอาข้อมูลเบื้องหลัง แล้ววาดบนหน้าเดิม (ไม่รีเฟรช)

---

## 5. ตัวอย่างการทำงาน 2 flow

### Flow A — ถามด้วยเสียง (บนหน้า `#/ask`)
```
1. กดไมค์ → เบราว์เซอร์ (MediaRecorder) อัดเสียง .webm     [AskDemo.jsx]
2. กดหยุด → POST /api/transcribe                          [app.py]
3. Whisper ถอด → "มอเตอร์ปั๊มไหม้ แก้ยังไง"                 [transcribe.py]
4. ข้อความไปโผล่ในช่องพิมพ์ (ยังไม่ตอบ!)
5. กดปุ่ม "ถาม" → POST /api/ask
6. bge-m3 ค้นเคสเกี่ยว → Typhoon เรียบเรียงตอบ            [rag.py]
7. คำตอบ + อ้างอิง case_id โผล่กล่องล่าง
```
> พูด "ฮัลโหล" → ได้ "สวัสดีครับ" = ปกติ. คำทักทายไม่ใช่คำถามซ่อมเครื่อง Typhoon เลยทักกลับ

### Flow B — บันทึกเคสจากคลิป (บนหน้า `#/stt` หรือ pipeline)
```
เสียง → Whisper ถอด → Typhoon extract เป็น JSON → render .md → เขียนลง vault
                                                                  [vault.py]
```

---

## 6. รัน + แก้โค้ด

### รันปกติ (1 คำสั่ง)
```bash
cd backend
.\.venv\Scripts\python.exe app.py      # http://127.0.0.1:5000
```

### แก้ UI แบบ live reload (เพิ่มอีกจอ)
```bash
cd frontend
npm run dev                            # :5173 (proxy /api → :5000)
```

### เมื่อไหร่ต้อง build / restart
```
แก้ .jsx/.css  → npm run build         (ถ้าไม่ได้เปิด dev :5173 — ให้ :5000 เห็น)
แก้ .py        → auto (reload=True จับเอง)
แก้ .env       → restart backend มือ    (dotenv โหลดครั้งเดียวตอน start)
pip install    → restart backend มือ
แก้ .md ใน vault → ไม่ต้องทำอะไร         (RAG อ่านสดทุก request)
```

---

## 7. Mock / graceful degradation (สำคัญ)

ทุกโมเดลออกแบบให้ **รันได้แม้ backend ไม่พร้อม** — คืนข้อมูลปลอมแทน error
- เห็น `[MOCK — ...]` หรือ badge "MOCK" = **backend จริงไม่ติด** (ไม่ใช่โค้ดพัง)
- เช็ค `.env` / server reachability ก่อน "แก้บั๊ก"

เช็คเร็ว:
```bash
ollama ps                              # Typhoon + bge โหลดอยู่มั้ย
curl http://127.0.0.1:5000/api/health  # server ตื่นมั้ย
nvidia-smi                             # VRAM เหลือมั้ย (รวม ~11/12GB)
```

---

## 8. Config หลัก (`backend/.env`)

| ตัวแปร | ค่าปัจจุบัน | คืออะไร |
|--------|------------|---------|
| `QWEN_MODEL` | `scb10x/llama3.1-typhoon2-8b-instruct` | LLM (extract + ตอบ) |
| `QWEN_BASE_URL` | `http://127.0.0.1:11434/v1` | ที่อยู่ Ollama (OpenAI-compatible) |
| `EMBED_MODEL` | `bge-m3` | โมเดลค้นหา |
| `WHISPER_MODEL` | `large-v3` | โมเดลถอดเสียง (แม่นสุดสำหรับไทย) |
| `WHISPER_DEVICE` | `cuda` | ใช้ GPU |
| `VAULT_PATH` | (path Obsidian) | ที่เก็บไฟล์ `.md` |

> ชื่อ `QWEN_*` เป็นชื่อเก่า (เริ่มจาก Qwen แล้วเปลี่ยนมา Typhoon) — ยังใช้ได้เพราะเป็น OpenAI-compatible

---

*ไฟล์นี้เป็น guideline สรุป. โค้ดจริง + คอมเมนต์ภาษาไทยอยู่ในแต่ละไฟล์. สเปกระบบเต็ม (Django/MSSQL ที่วางแผนไว้) อยู่ใน `docs/`*
