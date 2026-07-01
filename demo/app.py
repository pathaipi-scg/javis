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
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
import os, sys, tempfile, re, time, shutil

from transcribe import transcribe_audio, WHISPER_MODEL, WHISPER_DEVICE, STT_BASE_URL
import rag, llm, tts

# บน Windows stdout ของ uvicorn เป็น cp1252 -> print ภาษาไทยใน except (log) จะ crash เอง
# แล้วทำให้ graceful-degradation (คืน None/mock) กลายเป็น HTTP 500 แทน -> ตั้ง utf-8 กันไว้
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

app = FastAPI()
templates = Jinja2Templates(directory="templates")
UPLOAD = tempfile.gettempdir()


def _save_upload(upload) -> str:
    """เซฟไฟล์ที่อัปโหลด (Starlette UploadFile) ลง temp แล้วคืน path"""
    path = os.path.join(UPLOAD, upload.filename)
    with open(path, "wb") as out:
        shutil.copyfileobj(upload.file, out)
    return path


@app.api_route("/", methods=["GET", "POST"], response_class=HTMLResponse)
async def index(request: Request):
    """หน้าป้อนข้อมูล = ฟอร์มเพิ่มเคส (tag-first). POST = บันทึกเคสตามสเปก"""
    saved = None
    if request.method == "POST":
        f = await request.form()
        tags = [t.lstrip("#").strip() for t in re.split(r"[,\s]+", f.get("tags", "")) if t.strip()]

        # เสียง (ถ้าแนบ) -> ถอดเป็นข้อความ เติมต่อท้ายช่อง "อาการ"
        # dropdown โรงงาน/ฝ่าย: ถ้าเลือก "เพิ่มใหม่" (__new__) ใช้ค่าที่พิมพ์ในช่อง *_new แทน
        plant = f.get("plant", "").strip()
        if plant == "__new__":
            plant = f.get("plant_new", "").strip()
        department = f.get("department", "").strip()
        if department == "__new__":
            department = f.get("department_new", "").strip()

        symptom = f.get("symptom", "").strip()
        audio = f.get("audio")
        if audio and audio.filename:
            apath = _save_upload(audio)
            transcript = await run_in_threadpool(transcribe_audio, apath)
            symptom = (symptom + "\n" + transcript).strip() if symptom else transcript

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
        }
        # รูปประกอบ (แค่แนบ ไม่ส่งเข้า AI)
        image = f.get("image")
        image_path = image_name = None
        if image and image.filename:
            image_name = image.filename
            image_path = _save_upload(image)
        status, case_id = await run_in_threadpool(rag.save_case_and_reindex, fields, image_path, image_name)
        if case_id:
            saved = {"case_id": case_id, "written": status, "machine": fields["machine"]}
    return templates.TemplateResponse(request, "index.html",
                                      {"active": "capture", "saved": saved,
                                       "result": None, "tag_options": rag.all_tags(),
                                       "plant_options": rag.all_plants(),
                                       "dept_options": rag.all_departments()})


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
    return templates.TemplateResponse(request, "ask.html",
                                      {"active": "ask", "q": q, "answer": answer, "mock": used_mock,
                                       "plant": plant, "plants": rag.all_plants()})


@app.post("/tts")
async def tts_endpoint(request: Request):
    """อ่านคำตอบเป็นเสียง JARVIS (mp3). ถ้า edge-tts ใช้ไม่ได้ -> 503 ให้ฝั่งเว็บ fallback"""
    f = await request.form()
    audio = await tts.synthesize(f.get("text", ""))
    if audio is None:
        return Response(status_code=503)
    return Response(content=audio, media_type="audio/mpeg")


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
