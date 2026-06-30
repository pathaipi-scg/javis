"""
Demo เว็บ: รับไฟล์เสียงประชุม + รูปภาพ(พร้อม caption) -> ถอดข้อความ -> Qwen3-VL ดึงข้อมูลเครื่องจักร
-> แสดงผล + พรีวิว .md -> ปุ่ม Save เขียนลง Obsidian vault เดิม (ทาง A)

รัน:
    copy .env.example .env   (แล้วเติม QWEN_BASE_URL + VAULT_PATH)
    pip install -r requirements.txt
    python app.py
    เปิด http://127.0.0.1:5000
"""
from dotenv import load_dotenv
load_dotenv()  # โหลด .env ก่อน import โมดูลที่อ่าน env

from flask import Flask, render_template, request
import os, tempfile, re, time

from transcribe import transcribe_audio, WHISPER_MODEL, WHISPER_DEVICE, STT_BASE_URL
import rag, llm

app = Flask(__name__)
UPLOAD = tempfile.gettempdir()


@app.route("/", methods=["GET", "POST"])
def index():
    """หน้าป้อนข้อมูล = ฟอร์มเพิ่มเคส (tag-first). POST = บันทึกเคสตามสเปก"""
    saved = None
    if request.method == "POST":
        f = request.form
        tags = [t.lstrip("#").strip() for t in re.split(r"[,\s]+", f.get("tags", "")) if t.strip()]

        # เสียง (ถ้าแนบ) -> ถอดเป็นข้อความ เติมต่อท้ายช่อง "อาการ"
        symptom = f.get("symptom", "").strip()
        audio = request.files.get("audio")
        if audio and audio.filename:
            apath = os.path.join(UPLOAD, audio.filename)
            audio.save(apath)
            transcript = transcribe_audio(apath)
            symptom = (symptom + "\n" + transcript).strip() if symptom else transcript

        fields = {
            "machine": f.get("machine", "").strip(),
            "plant": f.get("plant", "").strip(),
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
        image = request.files.get("image")
        image_path = image_name = None
        if image and image.filename:
            image_name = image.filename
            image_path = os.path.join(UPLOAD, image_name)
            image.save(image_path)
        status, case_id = rag.save_case_and_reindex(fields, image_path, image_name)
        if case_id:
            saved = {"case_id": case_id, "written": status, "machine": fields["machine"]}
    return render_template("index.html", active="capture", saved=saved,
                           result=None, tag_options=rag.all_tags())


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

@app.route("/search", methods=["GET"])
def search():
    q = request.args.get("q", "").strip()
    results = []
    used_mock = False
    if q:
        # ของจริง: semantic search (bge-m3 + cosine) จากเคสใน vault
        results = rag.search(q)
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
    return render_template("search.html", active="search", q=q,
                           results=results, tag_facet=tag_facet, mock=used_mock)


@app.route("/dashboard", methods=["GET"])
def dashboard():
    # ของจริง: นับ/จัดกลุ่มจากเคสใน vault; ถ้าว่าง -> mock
    s = rag.stats()
    stats, categories = s if s else _MOCK_STATS
    return render_template("dashboard.html", active="dashboard",
                           stats=stats, categories=categories, mock=s is None)


@app.route("/ask", methods=["GET", "POST"])
def ask():
    q = request.form.get("q", "").strip() if request.method == "POST" else ""
    answer = None
    used_mock = False
    if q:
        # ของจริง: RAG = ค้นเคสที่เกี่ยว (bge-m3) -> Typhoon สรุป -> แนบ case_id
        answer = rag.answer(q)
        if answer is None:
            used_mock = True
            answer = {
                "text": "[MOCK] อาการแรงดันไฮดรอลิกตกของ Forming Press มักเกิดจากซีลวาล์วเสื่อม "
                        "วิธีแก้คือเปลี่ยนชุดซีลแล้วไล่ลมออกจากระบบ ใช้เวลาซ่อมราว 45 นาที",
                "citations": ["MTN-2026-0142", "MTN-2026-0098"],
            }
    return render_template("ask.html", active="ask", q=q, answer=answer, mock=used_mock)


@app.route("/stt", methods=["GET", "POST"])
def stt():
    """หน้าทดสอบ STT: อัปคลิป -> กดแปลง -> โชว์ข้อความที่ถอดได้
    ไว้วัดความแม่นของ Whisper กับเสียงจริง (ไม่เกี่ยวกับการบันทึกเคส)"""
    result = None
    if request.method == "POST":
        audio = request.files.get("audio")
        if audio and audio.filename:
            apath = os.path.join(UPLOAD, audio.filename)
            audio.save(apath)
            t0 = time.time()
            text = transcribe_audio(apath)
            stt_sec = round(time.time() - t0, 1)
            # ต่อท่อ: เอา transcript ไปให้ Typhoon สรุป/ดึงข้อมูลเครื่องจักร
            t1 = time.time()
            data = llm.extract_machines(text)
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
    return render_template("stt.html", active="stt", result=result, cfg=cfg)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
