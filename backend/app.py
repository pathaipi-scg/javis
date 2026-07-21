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

from fastapi import FastAPI, Request, Query, Header
from fastapi.responses import HTMLResponse, Response, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
import os, sys, tempfile, re, time, shutil, json

from transcribe import transcribe_audio, WHISPER_MODEL, WHISPER_DEVICE, STT_BASE_URL
import rag, llm, tts, vault, auth, km

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

# ─────────────────────────────────────────────────────────────
# ยาม /api/* — ต้องมี JWT ถึงจะผ่าน (ยกเว้นรายชื่อข้างล่าง)
# ทำเป็น middleware ไม่ใช่แปะทีละ endpoint เพราะ "ปิดเป็นค่าเริ่มต้น":
# เพิ่ม endpoint ใหม่วันหลัง = ถูกล็อคเองอัตโนมัติ ไม่ต้องกลัวลืมแปะ
# (ไฟล์ React /, /assets, /models, /fonts ไม่ได้ขึ้นต้นด้วย /api/ -> โหลดหน้า login ได้ตามปกติ)
# ─────────────────────────────────────────────────────────────
PUBLIC_API = {"/api/login", "/api/health"}


@app.middleware("http")
async def require_jwt(request: Request, call_next):
    path = request.url.path
    # OPTIONS = CORS preflight เบราว์เซอร์ยิงมาก่อนโดยไม่แนบ Authorization -> ต้องปล่อยผ่าน
    # ไม่งั้นหน้า React บน :5173 (dev) จะโดนบล็อกตั้งแต่ preflight เรียก API ไม่ได้เลย
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in PUBLIC_API:
        return await call_next(request)
    authz = request.headers.get("authorization", "")
    prefix = "bearer "
    if not authz.lower().startswith(prefix) or not auth.decode_token(authz[len(prefix):].strip()):
        return JSONResponse({"error": "ต้อง login ก่อน"}, status_code=401)
    return await call_next(request)


@app.on_event("startup")
async def _auth_status():
    """บอกจำนวนบัญชีที่อ่านได้จาก .env — เพิ่มคนใน .env แล้วเลขไม่ขึ้น = ยังไม่ได้ restart / ชื่อตัวแปรผิด"""
    print(auth.status_line())


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
    """อุ่นโมเดลตั้งแต่เปิด — คำถามแรกไม่เจอ cold (reranker + embed + index โหลดครั้งแรกช้า ~นาที)
    แยก try แต่ละ step: ถ้าใช้ Azure (ไม่รัน Typhoon local) การ ping local LLM จะล้ม
    แต่ต้อง 'ไม่บล็อก' การอุ่น bge/reranker/index ที่เป็นตัวทำคำถามแรกช้าจริง (ทำใน thread แยก)"""
    import threading

    def _step(name, fn):
        try:
            fn()
            print(f"[warm] {name} พร้อมใช้")
        except Exception as e:
            print(f"[warm] อุ่น {name} ไม่ได้ ({type(e).__name__}) — จะโหลดตอนถามแรกแทน")

    def _warm_local_llm():
        from llm import QWEN_MODEL
        rag._get_client().chat.completions.create(   # อุ่น LLM local: gen 1 token พอให้โหลดน้ำหนัก
            model=QWEN_MODEL, max_tokens=1,
            messages=[{"role": "user", "content": "hi /no_think"}])

    def _load():
        # เรียงจากตัวที่ทำคำถามแรกช้าสุดก่อน (reranker/index) — local LLM เป็นออปชัน อยู่ท้าย
        _step("reranker (CPU)", rag._get_reranker)   # โหลดครั้งแรกช้าสุด — ต้นเหตุคำถามแรก 58 วิ
        _step("bge-m3 embedding", lambda: rag._embed(["warm"]))
        _step("vault index", lambda: rag.search("warm"))  # embed เคสทั้งกอง + สร้าง index (cache)
        _step("local LLM", _warm_local_llm)          # ล้มได้ถ้าใช้ Azure — ไม่กระทบ step บน
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


# ประวัติค้นหาหน้า /search — log แยกไฟล์จากประวัติถาม-ตอบ (โครงเดียวกัน: JSONL)
SEARCH_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "search_history.jsonl")


def _log_search(q, plant, results, mock):
    """append คำค้น+สรุปผลลง log (พังเงียบ ไม่ให้กระทบการค้น)
    เก็บเฉพาะ top 3 พอให้ preview ในประวัติ — ไม่เก็บผลเต็ม กันไฟล์บวม"""
    try:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M"), "q": q, "plant": plant,
               "n": len(results),
               "top": [{"case_id": r["case_id"], "machine": r.get("machine", ""),
                        "score": r.get("score", 0)} for r in results[:3]],
               "mock": mock}
        with open(SEARCH_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_search_history(n=HISTORY_SHOW):
    """อ่าน log ค้นหา -> list ล่าสุดก่อน (ไม่เกิน n)"""
    try:
        with open(SEARCH_HISTORY_FILE, encoding="utf-8") as f:
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

_MOCK_BUBBLES = {"total": 5, "groups": [
    {"category": "hydraulic", "count": 2, "cases": [
        {"case_id": "MTN-2026-0142", "symptom": "แรงดันไฮดรอลิกตกเป็นระยะ เครื่องหยุดกลางรอบ",
         "cause": "ซีลวาล์ว V-203 เสื่อม มีลมในระบบ", "solution": "เปลี่ยนชุดซีล V-203 + ไล่ลม",
         "machine": "Forming Press", "component": "V-203", "repair_date": "2026-06-10",
         "severity": "high", "downtime_min": 45, "plant": "CB"},
        {"case_id": "MTN-2026-0098", "symptom": "ปั๊มไฮดรอลิกแรงดันไม่ขึ้น",
         "cause": "น้ำมันไฮดรอลิกต่ำ + วาล์วตัน", "solution": "ตรวจวาล์ว + เติมน้ำมันไฮดรอลิก",
         "machine": "Forming Press", "component": "Pump", "repair_date": "2026-06-12",
         "severity": "medium", "downtime_min": 30, "plant": "CB"}]},
    {"category": "electrical", "count": 2, "cases": [
        {"case_id": "MTN-2026-0120", "symptom": "มอเตอร์ปั๊มน้ำร้อนจัดจนไหม้",
         "cause": "แบริ่งฝืด โหลดเกิน", "solution": "เปลี่ยนมอเตอร์ + ตรวจแบริ่ง",
         "machine": "Water Pump", "component": "Motor", "repair_date": "2026-06-11",
         "severity": "high", "downtime_min": 90, "plant": "CB"},
        {"case_id": "MTN-2025-0331", "symptom": "หม้อแปลง 42KV รั่วไฟอ่อน",
         "cause": "ฉนวนเสื่อม", "solution": "Oil Test + เปลี่ยนฉนวน",
         "machine": "Transformer", "component": "42KV", "repair_date": "2026-06-10",
         "severity": "low", "downtime_min": 20, "plant": "CB"}]},
    {"category": "belt", "count": 1, "cases": [
        {"case_id": "MTN-2026-0077", "symptom": "สายพาน Kobelco ขาด 2 ครั้ง",
         "cause": "สายพานหมดอายุ", "solution": "เปลี่ยนสายพานชุดใหม่",
         "machine": "Kobelco", "component": "Belt", "repair_date": "2026-06-10",
         "severity": "medium", "downtime_min": 60, "plant": "CB"}]},
]}

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


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    employee_id: str
    email: str
    phone: str = ""          # optional
    role: str = "user"       # user | approver | admin


def _current_user(authorization: str):
    """ถอด token จาก header -> payload หรือ None (ใช้ซ้ำในหลาย endpoint)"""
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        return None
    return auth.decode_token(authorization[len(prefix):].strip())


@app.post("/api/login")
async def api_login(body: LoginIn):
    """login ด้วยบัญชีในตาราง users (MSSQL) -> คืน JWT แนบ header: Authorization: Bearer <token>

    ตอบ error กลางๆ เหมือนกันหมด ไม่บอกว่า "user ผิด" หรือ "รหัสผิด"
    (บอกแยก = ช่วยคนเดาว่ามี user นี้จริงไหม)
    """
    if not auth.auth_ready():
        # ไม่ตั้ง JWT_SECRET / ต่อ DB ไม่ได้ -> ปฏิเสธ (fail closed)
        print("[auth] ยังไม่พร้อม (JWT_SECRET หรือ DB) -> login ปิดไว้")
        return JSONResponse({"error": "auth ยังไม่พร้อมใช้งาน"}, status_code=503)
    user = auth.verify_login(body.username, body.password)
    if not user:
        return JSONResponse({"error": "username หรือ password ไม่ถูกต้อง"}, status_code=401)
    return {
        "access_token": auth.create_token(user),
        "token_type": "bearer",
        "expires_in": auth.JWT_EXPIRE_MIN * 60,
    }


@app.post("/api/register")
async def api_register(body: RegisterIn, authorization: str = Header("")):
    """เพิ่ม user ใหม่ — admin เท่านั้น (ตามฟอร์ม "Only admins can add new users")

    เช็คสิทธิ์จาก token จริง ไม่ใช่เชื่อค่าที่ frontend ส่งมา
    """
    payload = _current_user(authorization)
    if not payload:
        return JSONResponse({"error": "ต้อง login ก่อน"}, status_code=401)
    if payload.get("role") != "admin":
        return JSONResponse({"error": "เฉพาะ admin เท่านั้นที่เพิ่มผู้ใช้ได้"}, status_code=403)

    # validate ขั้นต่ำ
    required = {
        "username": body.username, "password": body.password,
        "first_name": body.first_name, "last_name": body.last_name,
        "employee_id": body.employee_id, "email": body.email,
    }
    missing = [k for k, v in required.items() if not (v or "").strip()]
    if missing:
        return JSONResponse({"error": f"กรอกไม่ครบ: {', '.join(missing)}"}, status_code=400)
    if body.role not in ("user", "approver", "admin"):
        return JSONResponse({"error": "role ไม่ถูกต้อง"}, status_code=400)

    clash = auth.username_exists(body.username, body.email, body.employee_id)
    if clash:
        label = {"username": "ชื่อผู้ใช้", "email": "อีเมล", "employee_id": "รหัสพนักงาน"}[clash]
        return JSONResponse({"error": f"{label}นี้มีอยู่แล้ว"}, status_code=409)

    try:
        new_id = auth.create_user(
            username=body.username.strip(), password=body.password,
            first_name=body.first_name.strip(), last_name=body.last_name.strip(),
            employee_id=body.employee_id.strip(), email=body.email.strip(),
            phone=(body.phone or "").strip() or None, role=body.role,
        )
    except Exception as e:
        print(f"[auth] register ล้มเหลว: {type(e).__name__}: {e}")
        return JSONResponse({"error": "เพิ่มผู้ใช้ไม่สำเร็จ"}, status_code=500)
    return {"id": new_id, "username": body.username, "role": body.role}


@app.get("/api/users")
async def api_users(authorization: str = Header("")):
    """รายชื่อ user ทั้งหมด (admin เท่านั้น) — ให้หน้า admin โชว์ตาราง"""
    payload = _current_user(authorization)
    if not payload:
        return JSONResponse({"error": "ต้อง login ก่อน"}, status_code=401)
    if payload.get("role") != "admin":
        return JSONResponse({"error": "เฉพาะ admin"}, status_code=403)
    return {"users": auth.list_users()}


@app.get("/api/me")
async def api_me(authorization: str = Header("")):
    """เช็คว่า token ยังใช้ได้ไหม (ให้ frontend ถามตอนเปิดหน้า) -> คืนข้อมูล user ใน token"""
    payload = _current_user(authorization)
    if not payload:
        return JSONResponse({"error": "token ไม่ถูกต้องหรือหมดอายุ"}, status_code=401)
    return {"username": payload.get("sub"), "role": payload.get("role"), "uid": payload.get("uid")}


# รายชื่อโมเดลให้ frontend ทำ dropdown — แยก local (Ollama) / api (คลาวด์)
# local: ค่า value = ชื่อโมเดลจริงที่ Ollama เสิร์ฟ (ส่งกลับมาใน /api/ask -> rag.answer)
# api:   ค่า value = "azure:<deployment>" — rag.py จะ route ไป Azure client
def _model_options():
    from llm import QWEN_MODEL
    from rag import AZURE_READY, AZURE_DEPLOYMENT, default_model
    api_models = []
    # ยิง Azure OpenAI ตรงจากแอป (เลน n8n proxy ยังมีในโค้ด rag.py แต่ไม่โชว์ใน dropdown)
    if AZURE_READY:
        api_models.append({
            "id": f"azure:{AZURE_DEPLOYMENT}",
            "label": "GPT-5.4 Mini (Azure)",
        })
    return {
        "local": [
            {"id": QWEN_MODEL, "label": "Typhoon 8B (ไทย)"},
        ],
        "api": api_models,
        # ถามจาก rag.default_model() เสมอ — ต้องเป็นตัวเดียวกับที่ /api/ask ใช้จริง
        # ตอนไม่ได้ส่ง model มา (ไม่งั้น dropdown โชว์อย่าง เซิร์ฟเวอร์ใช้อีกอย่าง)
        "default": default_model(),
    }


def _model_label(model_id):
    """map id โมเดล -> ป้ายอ่านง่าย (เช่น 'GPT-5.4 Mini (Azure)') สำหรับโชว์บนคำตอบ
    ถ้าไม่รู้จัก id คืน id ดิบไปเลย"""
    if not model_id:
        return ""
    opts = _model_options()
    for m in opts["local"] + opts["api"]:
        if m["id"] == model_id:
            return m["label"]
    return model_id


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
    # โมเดลที่ตอบจริง: ถ้าตอบสำเร็จใช้ค่าที่ rag คืนมา, ถ้า mock ใช้ค่าที่ผู้ใช้ขอ (เพื่อบอกว่าโมเดลที่เลือกต่อไม่ติด)
    used_id = answer.get("model") if not mock else (body.model.strip() or None)
    return {
        "answer": answer["text"],
        "citations": answer["citations"],
        "mock": mock,
        "seconds": seconds,
        "model": _model_label(used_id) or _model_label(_model_options()["default"]),
    }


def _mock_case(cid):
    """หาเคส mock จาก _MOCK_BUBBLES/_MOCK_SEARCH ตาม case_id (ใช้ตอน vault ว่าง)"""
    for g in _MOCK_BUBBLES["groups"]:
        for c in g["cases"]:
            if c["case_id"] == cid:
                return {**c, "category": g["category"], "tags": [g["category"]]}
    for c in _MOCK_SEARCH:
        if c["case_id"] == cid:
            return dict(c)
    return None


@app.get("/api/case/{case_id}")
async def api_case(case_id: str):
    """ดึงรายละเอียดเคสเดียวจาก case_id (ให้ citation ในคำตอบคลิก/โชว์ข้างได้)
    หาในเคสจริงก่อน (rag.load_cases) ถ้าไม่เจอ/vault ว่าง -> ตกไป mock"""
    cid = (case_id or "").strip()
    if not cid:
        return JSONResponse({"error": "no case_id"}, status_code=400)
    try:
        # get_case รวมทั้งเคส MTN และเอกสาร KM -> citation KM คลิกดูได้เหมือนเคส
        c = await run_in_threadpool(rag.get_case, cid)
    except Exception:
        c = None
    if c:
        return {"found": True, "mock": False, "case": c}
    mc = _mock_case(cid)
    if mc:
        return {"found": True, "mock": True, "case": mc}
    return JSONResponse({"found": False, "case": None}, status_code=404)


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


@app.get("/api/search-history")
async def api_search_history():
    """ประวัติค้นหาล่าสุด (ใหม่ก่อน) — ให้ sidebar หน้า /search"""
    return {"history": _load_search_history()}


@app.post("/api/search-history/clear")
async def api_search_history_clear():
    """ลบประวัติค้นหาทั้งหมด"""
    try:
        os.remove(SEARCH_HISTORY_FILE)
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
async def api_search(q: str = "", plant: str = "", log: int = 1):
    """ค้นเคส semantic (bge-m3) — เวอร์ชัน JSON ของ /search
    log=0 -> ค้นสดขณะพิมพ์ (realtime) ไม่บันทึกประวัติ กันสแปมทุกคีย์"""
    q = q.strip()
    plant = plant.strip()
    if not q:
        return {"results": [], "tag_facet": [], "mock": False}
    results = await run_in_threadpool(rag.search, q, 8, plant or None)
    mock = results is None
    if mock:
        results = _MOCK_SEARCH
    if log:
        _log_search(q, plant, results, mock)
    facet = {}
    for r in results:
        for t in r["tags"]:
            facet[t] = facet.get(t, 0) + 1
    tag_facet = sorted(facet.items(), key=lambda x: -x[1])
    return {"results": results, "tag_facet": tag_facet, "mock": mock}


@app.get("/api/bubbles")
async def api_bubbles(plant: str = "", date_from: str = Query("", alias="from"),
                      date_to: str = Query("", alias="to")):
    """เคสจริงจัดกลุ่มตาม category สำหรับหน้า bubble dashboard (#/dashboard)
    กรองด้วย ?plant=&from=YYYY-MM-DD&to=YYYY-MM-DD (ว่าง = ไม่กรอง)"""
    b = await run_in_threadpool(rag.bubbles, plant or None, date_from or None, date_to or None)
    mock = b is None
    if mock:
        b = _MOCK_BUBBLES
    return {"groups": b["groups"], "total": b["total"], "mock": mock}


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
    synthesize คืน (bytes, media_type) — gemini/windows = audio/wav"""
    f = await request.form()
    result = await tts.synthesize(f.get("text", ""))
    if result is None:
        return Response(status_code=503)
    audio, media_type = result
    return Response(content=audio, media_type=media_type)


@app.post("/api/tts-stream")
async def tts_stream_endpoint(request: Request):
    """สตรีมเสียง (mp3) ทยอยส่ง -> เสียงแรก ~0.8s (เร็วกว่ารอทั้งก้อน).
    เฉพาะ engine=openai ; engine อื่น -> ตกไป synthesize เต็มก้อนเหมือน /api/tts"""
    f = await request.form()
    text = (f.get("text") or "").strip()
    if not text:
        return Response(status_code=400)
    if tts.TTS_ENGINE == "openai":
        # Starlette วน sync generator ใน threadpool เอง (ไม่บล็อก event loop)
        # error กลางสตรีม -> สตรีมขาด -> ฝั่งเว็บ fallback เสียงเบราว์เซอร์
        return StreamingResponse(tts.stream_openai(text), media_type="audio/mpeg")
    # engine อื่น: เต็มก้อน
    result = await tts.synthesize(text)
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
# KM (Knowledge Management) — อัปโหลดเอกสาร -> PNG -> train เป็นบทสรุป (แทน scg-km-webchat + n8n)
# บทสรุปเข้า index เดียวกับเคส -> ถามที่หน้าแรกเจอทั้ง KM และเคส MTN
# ─────────────────────────────────────────────────────────────
def _reindex_cache():
    """ล้าง cache ของ rag เพื่อให้ index ใหม่ (เคส+KM) รอบถามถัดไป"""
    rag._CACHE.update(key=None, cases=None, vecs=None, vocab=None)


@app.get("/api/km/folders")
async def api_km_folders():
    """โครงโฟลเดอร์ใน vault (ไว้เลือกที่เก็บตอนอัปโหลด)"""
    tree = await run_in_threadpool(vault.list_vault_tree)
    return {"tree": tree}


@app.post("/api/km/folders")
async def api_km_folder_create(request: Request):
    """สร้างโฟลเดอร์ใหม่ใน vault (ปุ่ม 'เพิ่มโฟลเดอร์')"""
    body = await request.json()
    rel = (body.get("path") or "").strip()
    if not rel:
        return JSONResponse({"error": "no path"}, status_code=400)
    try:
        created = await run_in_threadpool(vault.make_folder, rel)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "path": created}


@app.post("/api/km/upload")
async def api_km_upload(request: Request):
    """อัปโหลดเอกสารเข้า vault + แปลงทุกหน้าเป็น PNG (Word/PDF/PPT/Excel)
    multipart: file (หลายไฟล์ได้) + targetPath + category + machine"""
    f = await request.form()
    files = f.getlist("file")
    files = [x for x in files if getattr(x, "filename", "")]
    if not files:
        return JSONResponse({"error": "no file"}, status_code=400)
    target = (f.get("targetPath") or "").strip()
    category = (f.get("category") or "").strip()
    machine = (f.get("machine") or "").strip()

    def _one(tmp_path, filename):
        # เขียนไฟล์ดิบ + metadata + asset folder แล้วแปลง PNG
        res = vault.save_km_upload(target, tmp_path, filename, category, machine)
        asset_abs = vault._vault_join(res["asset_rel"])
        pngs = km.convert_to_png(tmp_path, str(asset_abs))
        vault.set_km_converted(res["meta_rel"], res["km_id"], len(pngs))
        return {"km_id": res["km_id"], "source_file": filename,
                "png_count": len(pngs), "folder": res["folder"],
                "ok": len(pngs) > 0}

    results = []
    for up in files:
        tmp = _save_upload(up)
        try:
            results.append(await run_in_threadpool(_one, tmp, up.filename))
        except Exception as e:
            results.append({"source_file": up.filename, "ok": False, "error": str(e)})
    return {"results": results}


@app.get("/api/km/list")
async def api_km_list():
    """รายการ KM doc ทั้งหมด + สถานะ (โชว์ในหน้า KM)"""
    docs = await run_in_threadpool(vault.find_km_docs)
    return {"docs": docs}


@app.get("/api/km/not-trained")
async def api_km_not_trained():
    """KM ที่แปลง PNG แล้วแต่ยังไม่ train"""
    docs = await run_in_threadpool(vault.find_km_docs)
    todo = [d for d in docs if d.get("training_status") != "Trained" and d.get("png_count", 0) > 0]
    return {"docs": todo}


@app.get("/api/km/asset")
async def api_km_asset(path: str = Query("")):
    """เสิร์ฟรูป PNG ในหน้า KM (อยู่ใต้ /api/ = ต้อง JWT). กันพาธหลุดออกนอก vault"""
    from fastapi.responses import FileResponse
    try:
        p = vault._vault_join(path.strip())
    except Exception:
        return JSONResponse({"error": "bad path"}, status_code=400)
    if not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(p))


class KmTrainIn(BaseModel):
    km_ids: list[str] = []
    model: str = ""


def _train_stream(km_ids, model):
    """generator: train KM ทีละตัว ทีละหน้า -> yield NDJSON progress
    แต่ละหน้า analyze (Azure vision) -> รวม Slide Analysis -> summary -> ถ้า Morning Talk แตกเคส MTN"""
    docs = {d["km_id"]: d for d in vault.find_km_docs()}
    made_case = False
    for km_id in km_ids:
        d = docs.get(km_id)
        if not d:
            yield json.dumps({"type": "error", "km_id": km_id, "msg": "ไม่พบ KM"}) + "\n"
            continue
        asset_abs = vault._vault_join(d["folder"] + "/" + km_id)
        pngs = sorted(asset_abs.glob("Slide*.png"))
        total = len(pngs)
        yield json.dumps({"type": "start", "km_id": km_id, "slides": total}) + "\n"
        parts = []
        for i, png in enumerate(pngs, start=1):
            analysis = km.analyze_slide(str(png), model)
            parts.append(f"## Slide {i}\n{analysis}")
            yield json.dumps({"type": "slide", "km_id": km_id, "i": i, "n": total}) + "\n"
        analysis_md = "\n\n".join(parts)
        vault.set_km_trained(d["meta_rel"], analysis_md, total)
        # บทสรุปย่อ
        summary = km.summarize(analysis_md, model)
        vault.save_km_summary(d["folder"], km_id, summary,
                              category=d.get("category", ""), source_file=d.get("source_file", ""))
        # Morning Talk -> แตกเคส MTN เข้า cases/ (ดูจากชื่อโฟลเดอร์/พาธที่อัปโหลด ไม่ใช่ช่องหมวด)
        n_cases = 0
        path_l = (d.get("folder", "") + " " + d.get("target", "")).casefold().replace(" ", "")
        if "morning" in path_l:
            for c in km.extract_cases(analysis_md, model):
                fields = {
                    "machine": c.get("machine", ""), "component": c.get("component", ""),
                    "plant": "", "department": "", "line": "",
                    "source": f"KM {km_id}", "category": c.get("category", ""),
                    "severity": c.get("severity", "medium"), "status": "resolved",
                    "downtime_min": "", "parts_used": "", "tags": c.get("tags") or [],
                    "symptom": c.get("symptom", ""), "cause": c.get("cause", ""),
                    "solution": c.get("solution", ""), "result": c.get("result", ""),
                }
                _, cid = vault.save_case(fields)
                if cid:
                    n_cases += 1
                    made_case = True
        yield json.dumps({"type": "done", "km_id": km_id, "slides": total,
                          "cases": n_cases}) + "\n"
    _reindex_cache()   # KM summary (และเคสใหม่) เข้า index รอบถามถัดไป
    yield json.dumps({"type": "all_done"}) + "\n"


@app.post("/api/km/train")
async def api_km_train(body: KmTrainIn):
    """train KM ที่เลือก -> สตรีม progress ต่อหน้า (NDJSON). งานยาว = สตรีมดีกว่ารอทั้งก้อน"""
    if not body.km_ids:
        return JSONResponse({"error": "no km_ids"}, status_code=400)
    return StreamingResponse(_train_stream(body.km_ids, body.model.strip()),
                             media_type="application/x-ndjson")


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

    # โมเดล openWakeWord (public/models -> dist/models) — คำปลุก "hey jarvis" โหลดไฟล์นี้จาก /models/oww/*.onnx
    # ไม่ mount ตรงนี้ -> 404 บน :5000 (บน Vite :5173 public/ เสิร์ฟที่รากอยู่แล้วเลยไม่เจอปัญหา)
    _models_dir = os.path.join(FRONTEND_DIST, "models")
    if os.path.isdir(_models_dir):
        app.mount("/models", StaticFiles(directory=_models_dir), name="spa-models")

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
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
