"""
Backend (FastAPI) ของ JARVIS — คลังความรู้ซ่อมบำรุง

หน้าที่:
  - JSON API ทั้งหมดใต้ /api/* (ask/RAG, cases, search, dashboard, stt, transcribe, tts, history)
  - เสิร์ฟ React SPA (frontend/dist) ที่ราก "/" -> แอพเดียว พอร์ตเดียว
สมองอยู่ที่ transcribe.py / llm.py / rag.py / tts.py / vault.py

รัน:
    copy .env.example .env   (แล้วเติม QWEN_BASE_URL + VAULT_PATH)
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000
frontend dev (แก้ UI เห็นสด): cd ../frontend && npm run dev  (:5173 proxy /api -> :5000)
แก้ UI เสร็จ -> npm run build ให้ :5000 เห็นด้วย
"""
from dotenv import load_dotenv
load_dotenv()  # โหลด .env ก่อน import โมดูลที่อ่าน env

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from starlette.concurrency import run_in_threadpool
import os, sys, tempfile, re, time, shutil, json

from transcribe import transcribe_audio, WHISPER_MODEL, WHISPER_DEVICE, STT_BASE_URL
import rag, llm, tts, vault

# บน Windows stdout ของ uvicorn เป็น cp1252 -> print ภาษาไทยใน except (log) จะ crash เอง
# แล้วทำให้ graceful-degradation (คืน None/mock) กลายเป็น HTTP 500 แทน -> ตั้ง utf-8 กันไว้
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

app = FastAPI()

# อนุญาตให้ React dev server (Vite :5173) เรียก /api/* ได้ (ตอน build เสิร์ฟรวมแล้วไม่ต้องใช้)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD = tempfile.gettempdir()


@app.on_event("startup")
async def _warm_whisper():
    """โหลด Whisper เข้า GPU ตั้งแต่เปิด (background thread) — user คนแรกไม่เจอ cold ~4s
    ทำใน thread แยกเพื่อไม่บล็อกการ start server; ถ้าโหลดไม่ได้ก็ปล่อย (จะ lazy-load ตอน request แรกแทน)"""
    import threading
    from transcribe import _get_model
    def _load():
        try:
            _get_model()
            print("[warm] Whisper พร้อมใช้ (โหลดเข้า GPU แล้ว)")
        except Exception as e:
            print(f"[warm] โหลด Whisper ล่วงหน้าไม่ได้ ({type(e).__name__}) — จะโหลดตอน request แรกแทน")
    threading.Thread(target=_load, daemon=True).start()


@app.on_event("startup")
async def _warm_llm():
    """โหลด LLM (Typhoon/Qwen) + bge-m3 เข้า GPU ตั้งแต่เปิด — คำถามแรกไม่เจอ cold โหลดโมเดล
    ยิง ollama เปล่าๆ ครั้งเดียว (thread แยก ไม่บล็อก start); ต่อไม่ติดก็ปล่อย lazy-load ตอนถามแรก"""
    import threading
    def _load():
        try:
            from llm import QWEN_MODEL
            client = rag._get_client()
            client.chat.completions.create(          # อุ่น LLM: gen 1 token พอให้โหลดน้ำหนักเข้า GPU
                model=QWEN_MODEL, max_tokens=1,
                messages=[{"role": "user", "content": "hi /no_think"}])
            rag._embed(["warm"])                     # อุ่น bge-m3 (embedding)
            print(f"[warm] LLM ({QWEN_MODEL}) + bge พร้อมใช้ (โหลดเข้า GPU แล้ว)")
        except Exception as e:
            print(f"[warm] โหลด LLM/bge ล่วงหน้าไม่ได้ ({type(e).__name__}) — จะโหลดตอนถามแรกแทน")
    threading.Thread(target=_load, daemon=True).start()


def _save_upload(upload) -> str:
    """เซฟไฟล์ที่อัปโหลด (Starlette UploadFile) ลง temp แล้วคืน path"""
    path = os.path.join(UPLOAD, upload.filename)
    with open(path, "wb") as out:
        shutil.copyfileobj(upload.file, out)
    return path


# ประวัติถาม-ตอบหน้า /ask — เก็บเป็น JSONL (1 บรรทัด = 1 คำถาม) รอด restart
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ask_history.jsonl")
HISTORY_SHOW = 15  # จำนวนที่โชว์บนหน้า (ล่าสุดก่อน)


def _log_ask(q, plant, answer, mock):
    """append คำถาม+คำตอบลง log (พังเงียบ ไม่ให้กระทบการตอบ)"""
    try:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M"), "q": q, "plant": plant,
               "text": answer.get("text", ""), "citations": answer.get("citations", []),
               "mock": mock}
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_ask_history(n=HISTORY_SHOW):
    """อ่าน log -> list ล่าสุดก่อน (ไม่เกิน n)"""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            recs = [json.loads(x) for x in f if x.strip()]
        return list(reversed(recs))[:n]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# ค่า mock: ถ้า vault ว่าง/ต่อ model ไม่ติด -> /api/search, /api/dashboard ตกมาใช้ค่านี้
# ─────────────────────────────────────────────────────────────

_MOCK_SEARCH = [
    {"case_id": "MTN-2026-0142", "machine": "Forming Press",
     "symptom": "แรงดันไฮดรอลิกตกเป็นระยะ เครื่องหยุดกลางรอบ",
     "solution": "เปลี่ยนชุดซีล V-203 + ไล่ลม", "score": 91,
     "tags": ["hydraulic", "pressure-drop", "cutting"]},
    {"case_id": "MTN-2026-0098", "machine": "Forming Press",
     "symptom": "ปั๊มไฮดรอลิกแรงดันไม่ขึ้น",
     "solution": "ตรวจวาล์ว + เติมน้ำมันไฮดรอลิก", "score": 74,
     "tags": ["hydraulic", "pump"]},
    {"case_id": "MTN-2025-0331", "machine": "Press B",
     "symptom": "น้ำมันซึมที่วาล์ว แรงดันค่อยๆ ลด",
     "solution": "เปลี่ยนซีลวาล์ว", "score": 68,
     "tags": ["hydraulic", "leak"]},
]

_MOCK_STATS = ({"total": 142, "downtime": 3820, "machines": 27}, [
    {"name": "hydraulic", "count": 18},
    {"name": "motor / bearing", "count": 14},
    {"name": "electrical", "count": 9},
    {"name": "sensor", "count": 6},
    {"name": "pneumatic", "count": 4},
])


# ─────────────────────────────────────────────────────────────
# JSON API สำหรับ React frontend (frontend/) — dev proxy /api -> :5000
# ─────────────────────────────────────────────────────────────
from pydantic import BaseModel


class AskIn(BaseModel):
    question: str
    plant: str = ""      # จำกัดขอบเขตโรงงาน ("" = ทุกโรงงาน)
    model: str = ""      # โมเดลที่เลือกหน้าเว็บ ("" = ใช้ default ตาม .env)


# รายชื่อโมเดลให้ frontend ทำ dropdown — แยก local (Ollama) / api (คลาวด์ ยังไม่เปิด)
# local: ค่า value = ชื่อโมเดลจริงที่ Ollama เสิร์ฟ (ส่งกลับมาใน /api/ask -> rag.answer)
def _model_options():
    from llm import QWEN_MODEL
    return {
        "local": [
            {"id": QWEN_MODEL, "label": "Typhoon 8B (ไทย)"},
        ],
        "api": [],   # ยังไม่เปิด — เว้นไว้ให้ UI โชว์หัวข้อ (เพิ่มทีหลังตอนต่อ API คลาวด์)
        "default": QWEN_MODEL,
    }


@app.get("/api/models")
async def api_models():
    """รายชื่อโมเดลที่เลือกได้ (local/api) — ให้หน้าแรกทำ dropdown เลือกโมเดล"""
    return _model_options()


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "service": "jarvis-maintenance-kb"}


@app.get("/api/plants")
async def api_plants():
    """รายชื่อโรงงานที่มีเคส — ให้ frontend ทำ dropdown"""
    return {"plants": await run_in_threadpool(rag.all_plants)}


@app.post("/api/ask")
async def api_ask(body: AskIn):
    """ถาม JARVIS (RAG จากเคสจริง) — ตัวเดียวกับหน้า /ask แต่คืน JSON"""
    q = body.question.strip()
    if not q:
        return JSONResponse({"error": "no question"}, status_code=400)
    plant = body.plant.strip()
    t0 = time.perf_counter()
    answer = await run_in_threadpool(rag.answer, q, 4, plant or None, body.model.strip() or None)
    seconds = round(time.perf_counter() - t0, 1)   # เวลาที่ LLM ใช้ตอบ (ค้น + สร้างคำตอบ)
    mock = answer is None
    if mock:
        answer = {
            "text": "[MOCK] อาการแรงดันไฮดรอลิกตกของ Forming Press มักเกิดจากซีลวาล์วเสื่อม "
                    "วิธีแก้คือเปลี่ยนชุดซีลแล้วไล่ลมออกจากระบบ ใช้เวลาซ่อมราว 45 นาที",
            "citations": ["MTN-2026-0142", "MTN-2026-0098"],
        }
    _log_ask(q, plant, answer, mock)
    return {"answer": answer["text"], "citations": answer["citations"], "mock": mock, "seconds": seconds}


@app.get("/api/history")
async def api_history():
    """ประวัติถาม-ตอบล่าสุด (ใหม่ก่อน) — log ตัวเดียวกับหน้า Jinja"""
    return {"history": _load_ask_history()}


@app.post("/api/history/clear")
async def api_history_clear():
    """ลบประวัติทั้งหมด (เวอร์ชัน JSON ของ /ask/clear)"""
    try:
        os.remove(HISTORY_FILE)
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/form-options")
async def api_form_options():
    """ตัวเลือกของฟอร์มป้อนเคส (tag/โรงงาน/ฝ่าย จากเคสจริง + ค่าคงที่)"""
    return {
        "tags": await run_in_threadpool(rag.all_tags),
        "plants": await run_in_threadpool(rag.all_plants),
        "departments": await run_in_threadpool(rag.all_departments),
        "severities": ["low", "medium", "high"],
        "statuses": ["open", "resolved"],
        "sources": ["morning_meeting", "หน้างาน", "อื่นๆ"],
    }


@app.post("/api/cases/preview")
async def api_case_preview(request: Request):
    """สร้างพรีวิว .md จากฟอร์ม (ยังไม่เขียนดิสก์) — เวอร์ชัน JSON ของ POST /
    รับ multipart: field เดียวกับหน้า Jinja + audio (ถอดต่อท้ายอาการ) + image (แนบ)"""
    f = await request.form()
    tags = [t.lstrip("#").strip() for t in re.split(r"[,\s]+", f.get("tags", "")) if t.strip()]

    # เสียง (ถ้าแนบ) -> ถอดเป็นข้อความ เติมต่อท้ายช่อง "อาการ"
    symptom = (f.get("symptom") or "").strip()
    audio = f.get("audio")
    if audio and getattr(audio, "filename", ""):
        apath = _save_upload(audio)
        transcript = await run_in_threadpool(transcribe_audio, apath)
        symptom = (symptom + "\n" + transcript).strip() if symptom else transcript

    # รูปประกอบ (แค่แนบ ไม่ส่งเข้า AI) -> เซฟ temp ก่อน ค่อยก๊อปเข้า vault ตอนยืนยัน
    image = f.get("image")
    image_path = image_name = None
    if image and getattr(image, "filename", ""):
        image_name = image.filename
        image_path = _save_upload(image)

    fields = {
        "machine": (f.get("machine") or "").strip(),
        "plant": (f.get("plant") or "").strip(),
        "department": (f.get("department") or "").strip(),
        "line": (f.get("line") or "").strip(),
        "component": (f.get("component") or "").strip(),
        "category": tags[0] if tags else "",
        "severity": (f.get("severity") or "").strip(),
        "status": (f.get("status") or "").strip(),
        "downtime_min": (f.get("downtime_min") or "").strip(),
        "parts_used": (f.get("parts_used") or "").strip(),
        "source": (f.get("source") or "").strip(),
        "tags": tags,
        "symptom": symptom,
        "cause": f.get("cause", ""),
        "solution": f.get("solution", ""),
        "result": f.get("result", ""),
        "caption": f.get("caption", ""),
        "image_name": image_name,
    }
    case_id, md = await run_in_threadpool(vault.render_case, fields)
    return {"case_id": case_id, "md": md, "symptom": symptom,
            "image_name": image_name or "", "image_path": image_path or ""}


@app.get("/api/search")
async def api_search(q: str = "", plant: str = ""):
    """ค้นเคส semantic (bge-m3) — เวอร์ชัน JSON ของ /search"""
    q = q.strip()
    plant = plant.strip()
    if not q:
        return {"results": [], "tag_facet": [], "mock": False}
    results = await run_in_threadpool(rag.search, q, 8, plant or None)
    mock = results is None
    if mock:
        results = _MOCK_SEARCH
    facet = {}
    for r in results:
        for t in r["tags"]:
            facet[t] = facet.get(t, 0) + 1
    tag_facet = sorted(facet.items(), key=lambda x: -x[1])
    return {"results": results, "tag_facet": tag_facet, "mock": mock}


@app.get("/api/dashboard")
async def api_dashboard():
    """ตัวเลขสรุป + จำนวนตามหมวด — เวอร์ชัน JSON ของ /dashboard"""
    s = await run_in_threadpool(rag.stats)
    stats, categories = s if s else _MOCK_STATS
    return {"stats": stats, "categories": categories, "mock": s is None}


def _mock_graph():
    """กราฟตัวอย่าง — โชว์ตอน vault ว่าง (โครงเดียวกับ rag.graph())"""
    nodes, links = [], []
    add = lambda i, t, b="": nodes.append({"id": i, "type": t, "body": b})
    lk = lambda a, b: links.append({"source": a, "target": b})
    add("CB", "plant", "โรงงาน CB"); add("SB1-1", "plant", "โรงงาน SB1-1")
    for m, p in [("Forming-Press", "CB"), ("Sheet-Cutter", "CB"),
                 ("Conveyor-A", "SB1-1"), ("Mixer", "SB1-1")]:
        add(m, "machine", f"เครื่อง {m} @ {p}"); lk(m, p)
    for c, m in [("V-203-Valve", "Forming-Press"), ("Cutting-Blade", "Sheet-Cutter"),
                 ("Bearing-6204", "Conveyor-A"), ("Gearbox", "Mixer")]:
        add(c, "component", f"อะไหล่ {c} ของ {m}"); lk(c, m)
    for f in ["hydraulic", "blade-wear", "bearing"]:
        add(f, "fault", f"ประเภทปัญหา: {f}")
    add("Team-A", "team", "ทีมซ่อมบำรุง A"); add("Team-B", "team", "ทีมซ่อมบำรุง B")
    for cid, m, c, f, t, body in [
        ("MTN-2026-0142", "Forming-Press", "V-203-Valve", "hydraulic", "Team-A",
         "อาการ: แรงดันไฮดรอลิกตก\nสาเหตุ: ซีลวาล์ว V-203 รั่ว\nวิธีแก้: เปลี่ยนชุดซีล + ไล่ลม"),
        ("MTN-2026-0138", "Sheet-Cutter", "Cutting-Blade", "blade-wear", "Team-B",
         "อาการ: ใบมีดสึกเร็ว\nวิธีแก้: เปลี่ยนใบใหม่ + ปรับ feed rate"),
        ("MTN-2026-0131", "Conveyor-A", "Bearing-6204", "bearing", "Team-A",
         "อาการ: แบริ่งมีเสียงดัง\nวิธีแก้: อัดจารบี + เปลี่ยนลูกปืน"),
        ("MTN-2026-0125", "Mixer", "Gearbox", "bearing", "Team-B",
         "อาการ: เกียร์ร้อนผิดปกติ\nวิธีแก้: เปลี่ยนน้ำมันเกียร์"),
    ]:
        add(cid, "case", body); lk(cid, m); lk(cid, c); lk(cid, f); lk(cid, t)
    return {"nodes": nodes, "links": links}


@app.get("/api/graph")
async def api_graph():
    """ข้อมูล knowledge graph จากเคสจริงใน vault — ให้หน้า #/graph วาด d3"""
    g = await run_in_threadpool(rag.graph)
    mock = g is None
    if mock:
        g = _mock_graph()
    return {"nodes": g["nodes"], "links": g["links"], "mock": mock}


@app.get("/api/stt-config")
async def api_stt_config():
    """ค่าคอนฟิก STT (โมเดล/อุปกรณ์/remote) ให้หน้าทดสอบโชว์"""
    return {"model": WHISPER_MODEL, "device": WHISPER_DEVICE, "remote": bool(STT_BASE_URL)}


@app.post("/api/stt")
async def api_stt(request: Request):
    """ทดสอบ STT: อัปคลิป -> ถอด (Whisper) -> ดึงข้อมูลเครื่อง (Typhoon) -> JSON
    ไว้วัดความแม่นของ Whisper กับเสียงจริง — เวอร์ชัน JSON ของหน้า /stt เดิม"""
    f = await request.form()
    audio = f.get("audio")
    if not (audio and getattr(audio, "filename", "")):
        return JSONResponse({"error": "no audio"}, status_code=400)
    apath = _save_upload(audio)
    t0 = time.time()
    text = await run_in_threadpool(transcribe_audio, apath)
    stt_sec = round(time.time() - t0, 1)
    t1 = time.time()
    data = await run_in_threadpool(llm.extract_machines, text)
    return {
        "filename": audio.filename,
        "text": text,
        "seconds": stt_sec,
        "is_mock": text.lstrip().startswith("[MOCK"),
        "summary": data.get("summary", ""),
        "machines": data.get("machines", []),
        "llm_seconds": round(time.time() - t1, 1),
        "llm_mock": str(data.get("summary", "")).startswith("[MOCK"),
    }


class CaseSaveIn(BaseModel):
    md: str
    image_path: str = ""
    image_name: str = ""


@app.post("/api/cases/save")
async def api_case_save(body: CaseSaveIn):
    """ยืนยันบันทึกเคส (เนื้อ .md ที่อาจแก้ในพรีวิว) — เวอร์ชัน JSON ของ /save"""
    image_path = body.image_path.strip() or None
    image_name = body.image_name.strip() or None
    # กันพาธหลุด: อนุญาตก๊อปเฉพาะไฟล์ใน temp (ที่เพิ่งอัปโหลด) เท่านั้น
    if image_path and not os.path.abspath(image_path).startswith(os.path.abspath(UPLOAD)):
        image_path = None
    status, case_id = await run_in_threadpool(
        rag.save_markdown_and_reindex, body.md, image_path, image_name)
    return {"ok": bool(case_id), "case_id": case_id, "written": status}


@app.post("/tts")
@app.post("/api/tts")
async def tts_endpoint(request: Request):
    """อ่านคำตอบเป็นเสียง JARVIS. ถ้า TTS ใช้ไม่ได้ -> 503 ให้ฝั่งเว็บ fallback
    synthesize คืน (bytes, media_type) — windows=audio/wav, edge=audio/mpeg"""
    f = await request.form()
    result = await tts.synthesize(f.get("text", ""))
    if result is None:
        return Response(status_code=503)
    audio, media_type = result
    return Response(content=audio, media_type=media_type)


@app.post("/transcribe")
@app.post("/api/transcribe")
async def transcribe_endpoint(request: Request):
    """ถอดเสียงคำถาม (push-to-talk) -> คืน {text} เป็น JSON
    ใช้ที่หน้า /ask: กดพูด -> อัดเสียงในเบราว์เซอร์ -> ส่งมาถอด -> เติมช่องคำถามให้
    ถอดด้วย Whisper ตัวเดียวกับ pipeline (local/remote) — ตก mock ถ้าต่อ backend ไม่ได้"""
    f = await request.form()
    audio = f.get("audio")
    if not (audio and getattr(audio, "filename", "")):
        return JSONResponse({"error": "no audio"}, status_code=400)
    apath = _save_upload(audio)
    t0 = time.perf_counter()
    text = await run_in_threadpool(transcribe_audio, apath)
    seconds = round(time.perf_counter() - t0, 1)   # เวลาที่ใช้ถอดจริง
    # transcribe_audio ใส่ timestamp "[00.5s] ..." ต่อบรรทัด — คำถามสั้นๆ ไม่ต้องการ เลยตัดทิ้ง
    clean = re.sub(r"^\[[0-9.]+s\]\s*", "", text, flags=re.M).replace("\n", " ").strip()
    return {"text": clean, "seconds": seconds, "is_mock": text.lstrip().startswith("[MOCK")}


# ─────────────────────────────────────────────────────────────
# เสิร์ฟ React build (frontend/dist) ที่ราก -> แอพเดียว พอร์ตเดียวที่ :5000
# dev ใช้ Vite :5173 (HMR) proxy /api มาที่นี่ — แก้ UI เสร็จ `npm run build`
# ─────────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "frontend", "dist")

if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
              name="spa-assets")

    # ฟอนต์ self-host (public/fonts -> dist/fonts) — เสิร์ฟ woff2 จาก server เดียวกัน
    # ไม่พึ่ง Google Fonts; ถ้าไม่ mount ตรงนี้ /fonts/*.woff2 จะ 404 บน :5000
    _fonts_dir = os.path.join(FRONTEND_DIST, "fonts")
    if os.path.isdir(_fonts_dir):
        app.mount("/fonts", StaticFiles(directory=_fonts_dir), name="spa-fonts")

    @app.get("/", response_class=HTMLResponse)
    async def spa_root():
        """หน้าแรก = React app (routing ภายในเป็น hash #/ask #/case #/stt ...)"""
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    @app.get("/favicon.svg")
    async def spa_favicon():
        return FileResponse(os.path.join(FRONTEND_DIST, "favicon.svg"))
else:
    @app.get("/", response_class=PlainTextResponse)
    async def root_fallback():
        """ยังไม่ได้ build React — บอกวิธี build (API ที่ /api/* ยังใช้ได้ปกติ)"""
        return ("ยังไม่ได้ build frontend — รัน: cd ../frontend && npm install && npm run build\n"
                "แล้ว refresh หน้านี้ (API พร้อมใช้ที่ /api/*)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=5000, reload=True)
