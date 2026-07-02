"""
เรียก Qwen3 บน server คุณ ผ่าน OpenAI-compatible API (vLLM / Ollama / LM Studio ใช้รูปแบบเดียวกัน)
ตั้งค่า endpoint ที่ตัวแปรข้างล่าง หรือผ่าน env

ถ้าต่อ server ไม่ได้ -> คืน mock เพื่อให้ demo เดินต่อได้
"""
import os, json, base64, re
from dotenv import load_dotenv
load_dotenv()

# ===== ตั้งค่า server Qwen3 ของคุณตรงนี้ (override ได้ด้วย .env) =====
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "http://localhost:11434/v1")  # Ollama default; vLLM มักเป็น :8000/v1
QWEN_MODEL    = os.getenv("QWEN_MODEL", "qwen3")                         # เช่น qwen3, qwen3:8b, Qwen/Qwen3-8B
QWEN_API_KEY  = os.getenv("QWEN_API_KEY", "not-needed")                  # local มักไม่ต้องใช้
USE_VISION    = os.getenv("QWEN_VISION", "0") == "1"                     # เปิดถ้ารันรุ่น Qwen3-VL (ส่งรูปเข้าได้)
# ============================================

SYSTEM = "คุณคือผู้ช่วยดึงข้อมูลงานซ่อมบำรุงเครื่องจักรจากบันทึกประชุม ตอบเป็น JSON เท่านั้น"

PROMPT = """ดึงข้อมูลงานซ่อมบำรุงเครื่องจักรจากเนื้อหาต่อไปนี้ แล้วตอบกลับเป็น JSON เท่านั้น

ตัวอย่าง:
เนื้อหา: "เครื่อง B ปั๊มรั่วที่ห้องเครื่อง ซ่อม 2026-05-01 เปลี่ยนซีล"
ตอบ: {{"summary":"เครื่อง B ปั๊มรั่ว เปลี่ยนซีลแล้ว","machines":[{{"machine":"B","issue":"ปั๊มรั่ว","location":"ห้องเครื่อง","repair_date":"2026-05-01","action":"เปลี่ยนซีล"}}]}}

ตอนนี้ดึงจากเนื้อหานี้:
{context}

กฎ:
- ตอบ JSON เดียวเท่านั้น ห้ามมีข้อความอื่น
- "summary" = สรุปภาพรวมการประชุมเป็นภาษาไทย 1-2 ประโยค ห้ามเว้นว่างเด็ดขาด (ต้องพูดถึงเครื่องที่เจอและสถานะ)
- "machines" = รายการเครื่อง แต่ละตัวมีคีย์: machine, issue, location, repair_date, action
- ถ้าช่องไหนไม่ระบุ ให้เว้นเป็นสตริงว่าง"""


def _img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _normalize_base(url):
    """OpenAI client ต้องการ base ลงท้าย /v1 — เติมให้ถ้าลืม"""
    url = (url or "").rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def _mock_extract(context):
    """mock แบบอ่าน context จริง: จับ 'เครื่อง A/C/F...' แยกเป็นหลายเครื่อง
    ใช้ตอนยังต่อ Qwen ไม่ได้ — เพื่อทดสอบการแยกไฟล์ใน vault"""
    text = context or ""
    found = []
    # จับ "เครื่อง" ตามด้วยตัวอักษรอังกฤษ/เลข เช่น A, C, F, A1 (ไม่จับคำไทยอย่าง เครื่องจักร)
    for m in re.finditer(r"เครื่อง\s*([A-Za-z][0-9]?|[0-9]+)", text):
        name = m.group(1).upper()
        if name in [f["machine"] for f in found]:
            continue
        # เอาข้อความหลังชื่อเครื่อง (จนเจอเครื่องถัดไป/ขึ้นบรรทัด) มาเป็นอาการ
        rest = text[m.end():]
        issue = re.split(r"\n|เครื่อง", rest)[0].strip(" ,:-。.")
        found.append({
            "machine": name,
            "issue": issue or "(ไม่ระบุอาการ)",
            "location": "(ดูในประชุม)",
            "repair_date": "2026-06-25",
            "action": "(ดูในประชุม)",
        })
    if not found:
        found = [{"machine": "A", "issue": "มอเตอร์ไหม้", "location": "ปั๊มน้ำ",
                  "repair_date": "2026-06-20", "action": "เปลี่ยนมอเตอร์ใหม่"}]
    names = ", ".join(f["machine"] for f in found)
    return {"summary": f"[MOCK อ่าน caption] พบ {len(found)} เครื่อง: {names}",
            "machines": found}


_client = None


def _get_client():
    """OpenAI client ตัวเดียวใช้ซ้ำ (สร้างใหม่ทุก call บน Windows ช้าเพราะ localhost/IPv6)"""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=_normalize_base(QWEN_BASE_URL), api_key=QWEN_API_KEY)
    return _client


def extract_machines(context, image_path=None):
    """ป้อน context (transcript + caption) ให้ Qwen3 -> dict ข้อมูลเครื่องจักร"""
    try:
        client = _get_client()

        user_content = PROMPT.format(context=context or "(ไม่มีเนื้อหา)")

        if USE_VISION and image_path:
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{_img_b64(image_path)}"}},
                ]},
            ]
        else:
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_content},
            ]

        resp = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=messages,
            temperature=0,
        )
        text = resp.choices[0].message.content
        # ดึงเฉพาะก้อน JSON
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])

    except Exception:
        # fallback mock เพื่อให้ demo เดินต่อได้แม้ยังไม่ต่อ server
        # อ่าน context จริง → จับชื่อเครื่อง → แยกหลายเครื่องได้
        return _mock_extract(context)


def render_markdown(data, transcript="", image_note="", when=None, image_name=None):
    """สร้างพรีวิวไฟล์ .md แบบที่จะเขียนลง Obsidian vault"""
    import datetime as _dt
    when = when or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    day = when.split(" ")[0]
    machines = data.get("machines", [])
    fm_machines = ", ".join(m.get("machine", "") for m in machines)
    lines = [
        "---",
        f"date: {day}",
        f"datetime: {when}",
        "type: meeting",
        f"machines: [{fm_machines}]",
        "---",
        f"# ประชุม {when}",
        "",
        "## สรุป",
        data.get("summary", ""),
        "",
        "## เครื่องจักรที่พูดถึง",
    ]
    for m in machines:
        lines.append(
            f"- [[machine-{m.get('machine')}]] — {m.get('issue')} "
            f"({m.get('location')}) ซ่อม {m.get('repair_date')} / {m.get('action')}"
        )
    if image_note or image_name:
        lines += ["", "## หมายเหตุจากรูปภาพ"]
        if image_name:
            lines.append(f"![[{image_name}]]")   # ฝังรูปให้โชว์ใน Obsidian
        if image_note:
            lines.append(f"> {image_note}")
    if transcript:
        lines += ["", "## Transcript", "```", transcript.strip(), "```"]
    return "\n".join(lines)
