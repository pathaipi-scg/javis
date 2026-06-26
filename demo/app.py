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
import os, json, tempfile, datetime, base64, mimetypes, time

from transcribe import transcribe_audio
from llm import extract_machines, render_markdown
from vault import save_to_vault

app = Flask(__name__)
UPLOAD = tempfile.gettempdir()


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", result=None)


@app.route("/process", methods=["POST"])
def process():
    transcript = ""
    image_note = ""
    t_start = time.perf_counter()
    t_stt = 0.0

    # 1) ไฟล์เสียงประชุม -> ข้อความ
    audio = request.files.get("audio")
    if audio and audio.filename:
        path = os.path.join(UPLOAD, audio.filename)
        audio.save(path)
        _t0 = time.perf_counter()
        transcript = transcribe_audio(path)
        t_stt = time.perf_counter() - _t0

    # 2) รูปภาพ + caption ใต้รูป (เช่น รูปมอเตอร์ + "มอเตอร์เสีย")
    image = request.files.get("image")
    caption = request.form.get("caption", "").strip()
    image_path = None
    image_data_url = None
    if image and image.filename:
        image_path = os.path.join(UPLOAD, image.filename)
        image.save(image_path)
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        image_data_url = f"data:{mime};base64,{b64}"   # ฝังรูปไว้โชว์บนเว็บ
    if caption or image_path:
        image_note = caption or "(แนบรูปไม่มีคำอธิบาย)"

    # รวม context ป้อน LLM
    context = ""
    if transcript:
        context += f"# Transcript ประชุม\n{transcript}\n\n"
    if image_note:
        context += f"# หมายเหตุจากรูปภาพ\n{image_note}\n"

    # 3) Qwen3-VL ดึงข้อมูลเครื่องจักรเป็น JSON (ส่งรูปเข้าตรงๆ ถ้าเปิด vision)
    _t0 = time.perf_counter()
    data = extract_machines(context, image_path=image_path)
    t_llm = time.perf_counter() - _t0
    t_total = time.perf_counter() - t_start
    timing = {
        "stt": round(t_stt, 1),
        "llm": round(t_llm, 1),
        "total": round(t_total, 1),
    }

    # 4) พรีวิว .md (ใส่วันที่+เวลา)
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    when = now.strftime("%Y-%m-%d %H:%M")
    image_name = os.path.basename(image_path) if image_path else ""
    markdown = render_markdown(data, transcript, image_note, when=when, image_name=image_name)

    return render_template(
        "index.html",
        result={
            "transcript": transcript,
            "image_note": image_note,
            "image_data_url": image_data_url,
            "image_name": image_name,
            "image_tmp": image_path or "",
            "data": data,
            "markdown": markdown,
            "date": today,
            "datetime": when,
            "timing": timing,
            "machines_json": json.dumps(data.get("machines", []), ensure_ascii=False),
        },
    )


@app.route("/save", methods=["POST"])
def save():
    markdown = request.form.get("markdown", "")
    machines = json.loads(request.form.get("machines_json", "[]"))
    date = request.form.get("date", datetime.date.today().isoformat())
    when = request.form.get("datetime", "")
    image_tmp = request.form.get("image_tmp", "")
    image_name = request.form.get("image_name", "")
    status = save_to_vault(markdown, machines, date, when,
                           image_src=image_tmp, image_name=image_name)
    return render_template("index.html", result=None, save_status=status)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
