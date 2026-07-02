"""
Demo เว็บ: รับไฟล์เสียงประชุม + รูปภาพ(พร้อม caption) -> ถอดข้อความ -> Typhoon2 8B ดึงข้อมูลเครื่องจักร
-> แสดงผล + พรีวิว .md -> ปุ่ม Save เขียนลง Obsidian vault เดิม (ทาง A)

Backend = FastAPI (เดิมเป็น Flask) แต่ยังเสิร์ฟหน้าเดิมด้วย Jinja2 เหมือนเดิม
ทุก route/พฤติกรรมเท่าเดิม — Vue frontend ค่อยเสียบทีหลังเมื่อระบบนิ่ง

รัน:
    copy .env.example .env   (แล้วเติม QWEN_BASE_URL + VAULT_PATH)
    pip install -r requirements.txt
    python app.py
    เปิด http://127.0.0.1:5000
"""
from dotenv import load_dotenv
load_dotenv()  # โหลด .env ก่อน import โมดูลที่อ่าน env

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
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

templates = Jinja2Templates(directory="templates")
UPLOAD = tempfile.gettempdir()


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


# ช่องในฟอร์มที่ prefill กลับได้ (ตอนกด "ยกเลิก/กลับไปแก้" จากหน้าพรีวิว)
_FORM_FIELDS = ("machine", "plant", "department", "line", "component", "severity",
                "status", "downtime_min", "parts_used", "source",
                "tags", "symptom", "solution", "cause", "result", "caption")


def _form_ctx(saved=None, vals=None):
    """context ของหน้าฟอร์ม index.html (ตัวเลือก dropdown/tag + ค่า prefill)"""
    return {"active": "capture", "saved": saved, "result": None,
            "tag_options": rag.all_tags(), "plant_options": rag.all_plants(),
            "dept_options": rag.all_departments(), "vals": vals or {}}


@app.api_route("/", methods=["GET", "POST"], response_class=HTMLResponse)
async def index(request: Request):
    """หน้าป้อนข้อมูล (tag-first). POST = สร้างพรีวิว .md ให้ตรวจ/แก้ก่อน (ยังไม่เขียนดิสก์)"""
    if request.method == "POST":
        f = await request.form()
        # กด "ยกเลิก/กลับไปแก้" จากพรีวิว -> เด้งกลับฟอร์มโดยคงค่าเดิมไว้ (ไม่ล้าง)
        if f.get("action") == "edit":
            return templates.TemplateResponse(request, "index.html",
                                              _form_ctx(vals={k: f.get(k, "") for k in _FORM_FIELDS}))
        tags = [t.lstrip("#").strip() for t in re.split(r"[,\s]+", f.get("tags", "")) if t.strip()]

        # dropdown โรงงาน/ฝ่าย: ถ้าเลือก "เพิ่มใหม่" (__new__) ใช้ค่าที่พิมพ์ในช่อง *_new แทน
        plant = f.get("plant", "").strip()
        if plant == "__new__":
            plant = f.get("plant_new", "").strip()
        department = f.get("department", "").strip()
        if department == "__new__":
            department = f.get("department_new", "").strip()

        # เสียง (ถ้าแนบ) -> ถอดเป็นข้อความ เติมต่อท้ายช่อง "อาการ"
        symptom = f.get("symptom", "").strip()
        audio = f.get("audio")
        if audio and audio.filename:
            apath = _save_upload(audio)
            transcript = await run_in_threadpool(transcribe_audio, apath)
            symptom = (symptom + "\n" + transcript).strip() if symptom else transcript

        # รูปประกอบ (แค่แนบ ไม่ส่งเข้า AI) -> เซฟลง temp ไว้ก่อน ค่อยก๊อปเข้า vault ตอนยืนยัน
        image = f.get("image")
        image_path = image_name = None
        if image and image.filename:
            image_name = image.filename
            image_path = _save_upload(image)

        fields = {
            "machine": f.get("machine", "").strip(),
            "plant": plant,
            "department": department,
            "line": f.get("line", "").strip(),
            "component": f.get("component", "").strip(),
            # category: เอามาจาก tag แรกอัตโนมัติ (ไม่มีช่องให้กรอกแล้ว)
            "category": tags[0] if tags else "",
            "severity": f.get("severity", "").strip(),
            "status": f.get("status", "").strip(),
            "downtime_min": f.get("downtime_min", "").strip(),
            "parts_used": f.get("parts_used", "").strip(),
            "source": f.get("source", "").strip(),
            "tags": tags,
            "symptom": symptom,
            "cause": f.get("cause", ""),
            "solution": f.get("solution", ""),
            "result": f.get("result", ""),
            "caption": f.get("caption", ""),
            "image_name": image_name,
        }
        # สร้างพรีวิว .md (ยังไม่เขียนดิสก์) ให้ผู้ใช้ตรวจ/แก้ก่อน
        case_id, md = await run_in_threadpool(vault.render_case, fields)
        return templates.TemplateResponse(request, "preview.html",
                                          {"active": "capture", "md": md, "case_id": case_id,
                                           "plant": fields["plant"], "department": fields["department"],
                                           "image_name": image_name or "", "image_path": image_path or "",
                                           "f": fields, "tags_str": " ".join(fields.get("tags") or [])})
    return templates.TemplateResponse(request, "index.html", _form_ctx())


@app.post("/save", response_class=HTMLResponse)
async def save(request: Request):
    """ยืนยันบันทึกจากหน้าพรีวิว — เขียนเนื้อ .md (ที่อาจถูกแก้) ลง vault แล้ว index ใหม่"""
    f = await request.form()
    md = f.get("md", "")
    image_name = (f.get("image_name") or "").strip() or None
    image_path = (f.get("image_path") or "").strip() or None
    # กันพาธหลุด: อนุญาตก๊อปเฉพาะไฟล์ที่อยู่ใน temp (ที่เพิ่งอัปโหลด) เท่านั้น
    if image_path and not os.path.abspath(image_path).startswith(os.path.abspath(UPLOAD)):
        image_path = None
    status, case_id = await run_in_threadpool(rag.save_markdown_and_reindex, md, image_path, image_name)
    saved = None
    if case_id:
        saved = {"case_id": case_id, "written": status, "machine": vault._parse_fm(md).get("machine", "")}
    return templates.TemplateResponse(request, "index.html", _form_ctx(saved))


# ─────────────────────────────────────────────────────────────
# หน้า Serve (ด่าน 4): ค้นหา/ถาม-ตอบ/dashboard
# ของจริงทำผ่าน rag.py (bge-m3 + Typhoon + เคสใน vault)
# ถ้า vault ว่าง/ต่อ model ไม่ติด -> ตก mock ข้างล่างนี้แทน
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


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", plant: str = ""):
    q = q.strip()
    plant = plant.strip()
    results = []
    used_mock = False
    if q:
        # ของจริง: semantic search (bge-m3 + cosine) จากเคสใน vault; plant=กรองเฉพาะโรงงานนั้น
        results = await run_in_threadpool(rag.search, q, 8, plant or None)
        if results is None:
            # vault ว่าง/ต่อ embeddings ไม่ติด -> ตก mock เพื่อให้หน้าเดินต่อได้
            results = _MOCK_SEARCH
            used_mock = True
    # รวม tag จากผลลัพธ์เป็น facet
    facet = {}
    for r in results:
        for t in r["tags"]:
            facet[t] = facet.get(t, 0) + 1
    tag_facet = sorted(facet.items(), key=lambda x: -x[1])
    return templates.TemplateResponse(request, "search.html",
                                      {"active": "search", "q": q,
                                       "results": results, "tag_facet": tag_facet, "mock": used_mock,
                                       "plant": plant, "plants": rag.all_plants()})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    # ของจริง: นับ/จัดกลุ่มจากเคสใน vault; ถ้าว่าง -> mock
    s = await run_in_threadpool(rag.stats)
    stats, categories = s if s else _MOCK_STATS
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"active": "dashboard", "stats": stats,
                                       "categories": categories, "mock": s is None})


@app.api_route("/ask", methods=["GET", "POST"], response_class=HTMLResponse)
async def ask(request: Request):
    q = ""
    plant = ""
    if request.method == "POST":
        f = await request.form()
        q = f.get("q", "").strip()
        plant = f.get("plant", "").strip()
    answer = None
    used_mock = False
    if q:
        # ของจริง: RAG = ค้นเคสที่เกี่ยว (bge-m3) -> Typhoon สรุป -> แนบ case_id; plant=จำกัดขอบเขตโรงงาน
        answer = await run_in_threadpool(rag.answer, q, 4, plant or None)
        if answer is None:
            used_mock = True
            answer = {
                "text": "[MOCK] อาการแรงดันไฮดรอลิกตกของ Forming Press มักเกิดจากซีลวาล์วเสื่อม "
                        "วิธีแก้คือเปลี่ยนชุดซีลแล้วไล่ลมออกจากระบบ ใช้เวลาซ่อมราว 45 นาที",
                "citations": ["MTN-2026-0142", "MTN-2026-0098"],
            }
        _log_ask(q, plant, answer, used_mock)
    return templates.TemplateResponse(request, "ask.html",
                                      {"active": "ask", "q": q, "answer": answer, "mock": used_mock,
                                       "plant": plant, "plants": rag.all_plants(),
                                       "history": _load_ask_history()})


@app.post("/ask/clear")
async def ask_clear():
    """ลบประวัติถาม-ตอบทั้งหมด (ลบไฟล์ log) แล้วกลับไปหน้า /ask"""
    try:
        os.remove(HISTORY_FILE)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return RedirectResponse("/ask", status_code=303)


# ─────────────────────────────────────────────────────────────
# JSON API สำหรับ React frontend (frontend/ — Vite :5173 proxy /api มาที่นี่)
# สมองตัวเดียวกับหน้า Jinja ทุกอย่าง — ต่างแค่คืน JSON แทน HTML
# ─────────────────────────────────────────────────────────────
from pydantic import BaseModel


class AskIn(BaseModel):
    question: str
    plant: str = ""      # จำกัดขอบเขตโรงงาน ("" = ทุกโรงงาน)


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
    answer = await run_in_threadpool(rag.answer, q, 4, plant or None)
    mock = answer is None
    if mock:
        answer = {
            "text": "[MOCK] อาการแรงดันไฮดรอลิกตกของ Forming Press มักเกิดจากซีลวาล์วเสื่อม "
                    "วิธีแก้คือเปลี่ยนชุดซีลแล้วไล่ลมออกจากระบบ ใช้เวลาซ่อมราว 45 นาที",
            "citations": ["MTN-2026-0142", "MTN-2026-0098"],
        }
    _log_ask(q, plant, answer, mock)
    return {"answer": answer["text"], "citations": answer["citations"], "mock": mock}


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


@app.post("/tts")
@app.post("/api/tts")
async def tts_endpoint(request: Request):
    """อ่านคำตอบเป็นเสียง JARVIS (mp3). ถ้า edge-tts ใช้ไม่ได้ -> 503 ให้ฝั่งเว็บ fallback"""
    f = await request.form()
    audio = await tts.synthesize(f.get("text", ""))
    if audio is None:
        return Response(status_code=503)
    return Response(content=audio, media_type="audio/mpeg")


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
    text = await run_in_threadpool(transcribe_audio, apath)
    # transcribe_audio ใส่ timestamp "[00.5s] ..." ต่อบรรทัด — คำถามสั้นๆ ไม่ต้องการ เลยตัดทิ้ง
    clean = re.sub(r"^\[[0-9.]+s\]\s*", "", text, flags=re.M).replace("\n", " ").strip()
    return {"text": clean, "is_mock": text.lstrip().startswith("[MOCK")}


@app.api_route("/stt", methods=["GET", "POST"], response_class=HTMLResponse)
async def stt(request: Request):
    """หน้าทดสอบ STT: อัปคลิป -> กดแปลง -> โชว์ข้อความที่ถอดได้
    ไว้วัดความแม่นของ Whisper กับเสียงจริง (ไม่เกี่ยวกับการบันทึกเคส)"""
    result = None
    if request.method == "POST":
        f = await request.form()
        audio = f.get("audio")
        if audio and audio.filename:
            apath = _save_upload(audio)
            t0 = time.time()
            text = await run_in_threadpool(transcribe_audio, apath)
            stt_sec = round(time.time() - t0, 1)
            # ต่อท่อ: เอา transcript ไปให้ Typhoon สรุป/ดึงข้อมูลเครื่องจักร
            t1 = time.time()
            data = await run_in_threadpool(llm.extract_machines, text)
            result = {
                "filename": audio.filename,
                "text": text,
                "seconds": stt_sec,
                # transcribe_audio คืนสตริงขึ้นต้น "[MOCK" เมื่อยังต่อ Whisper ไม่ได้
                "is_mock": text.lstrip().startswith("[MOCK"),
                # ผลสรุปจาก Typhoon
                "summary": data.get("summary", ""),
                "machines": data.get("machines", []),
                "llm_seconds": round(time.time() - t1, 1),
                "llm_mock": str(data.get("summary", "")).startswith("[MOCK"),
            }
    cfg = {"model": WHISPER_MODEL, "device": WHISPER_DEVICE, "remote": bool(STT_BASE_URL)}
    return templates.TemplateResponse(request, "stt.html",
                                      {"active": "stt", "result": result, "cfg": cfg})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=5000, reload=True)
