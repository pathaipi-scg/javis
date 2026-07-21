"""
KM (Knowledge Management) — แปลงเอกสาร -> PNG + วิเคราะห์/สรุปด้วย LLM

พอร์ตฟีเจอร์จาก scg-km-webchat มาไว้ใน Jarvis แต่ **ไม่ใช้ n8n**:
  1. convert_to_png  — เอกสาร (pdf/ppt/word/excel) -> รูปทีละหน้า Slide001.png ...
                        PDF เรนเดอร์ตรงด้วย PyMuPDF; Office แปลงเป็น PDF ก่อนด้วย LibreOffice headless
  2. analyze_slide   — ส่ง PNG แต่ละหน้าเข้า Azure vision (gpt-5.4-mini) วิเคราะห์เป็น markdown ไทย
  3. summarize       — รวมผลวิเคราะห์ทุกหน้า -> บทสรุปย่อภาษาไทย
  4. extract_cases   — (เฉพาะ Morning Talk) แตกผลวิเคราะห์เป็นเคส MTN ป้อน vault.save_case

graceful degradation เหมือนโมดูลสมองตัวอื่น: ต่อ LLM/soffice ไม่ได้ -> คืน mock/[] ไม่ทำ server ล้ม
"""
import os
import re
import json
import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# แปลงเอกสาร -> PNG
# ─────────────────────────────────────────────────────────────
OFFICE_EXTS = {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = OFFICE_EXTS | PDF_EXTS

# ความละเอียดเรนเดอร์ (2.0 ~ 144 DPI เท่ากับ scg-km-webchat — อ่านตัวหนังสือในสไลด์ออก)
_ZOOM = float(os.getenv("KM_RENDER_ZOOM", "2.0"))


def find_soffice():
    """หา binary ของ LibreOffice (soffice). คืน path หรือ None ถ้าไม่พบ
    ลำดับ: env SOFFICE_BIN -> PATH -> ที่ติดตั้งมาตรฐานบน Windows"""
    env = os.getenv("SOFFICE_BIN", "").strip()
    if env and Path(env).exists():
        return env
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(p).exists():
            return p
    return None


def _office_to_pdf(src_path, out_dir):
    """แปลงไฟล์ Office -> PDF ด้วย LibreOffice headless. คืน path PDF หรือ None ถ้าแปลงไม่ได้
    ใช้ UserInstallation แยกต่อ process กัน lock เวลาแปลงหลายไฟล์พร้อมกัน"""
    soffice = find_soffice()
    if not soffice:
        return None
    src = Path(src_path)
    profile = Path(tempfile.gettempdir()) / f"lo_profile_{os.getpid()}"
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation=file:///{profile.as_posix()}",
             "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
            check=True, capture_output=True, timeout=180,
        )
    except Exception as e:
        print(f"[KM] LibreOffice แปลง {src.name} ไม่ได้ ({type(e).__name__}) — ข้ามไฟล์นี้")
        return None
    pdf = Path(out_dir) / (src.stem + ".pdf")
    return pdf if pdf.exists() else None


def _pdf_to_png(pdf_path, out_dir):
    """เรนเดอร์ทุกหน้าของ PDF -> Slide001.png, Slide002.png ... ใน out_dir. คืน list[Path]"""
    import fitz  # PyMuPDF
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pngs = []
    with fitz.open(pdf_path) as doc:
        mat = fitz.Matrix(_ZOOM, _ZOOM)
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat)
            fp = out / f"Slide{i:03d}.png"
            pix.save(str(fp))
            pngs.append(fp)
    return pngs


def convert_to_png(src_path, out_dir):
    """แปลงเอกสาร 1 ไฟล์ -> รูปทีละหน้าใน out_dir. คืน list[Path] ของ PNG (Slide001.png...)
    PDF -> เรนเดอร์ตรง; Office -> LibreOffice แปลงเป็น PDF ก่อน. แปลงไม่ได้ -> คืน [] (ไม่ throw)"""
    ext = Path(src_path).suffix.lower()
    try:
        if ext in PDF_EXTS:
            return _pdf_to_png(src_path, out_dir)
        if ext in OFFICE_EXTS:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = _office_to_pdf(src_path, tmp)
                if not pdf:
                    return []
                return _pdf_to_png(pdf, out_dir)
    except Exception as e:
        print(f"[KM] convert_to_png ล้มเหลว ({type(e).__name__}: {e})")
    return []


# ─────────────────────────────────────────────────────────────
# LLM: วิเคราะห์สไลด์ / สรุป / แตกเคส  (แทน n8n md_pic / md_summary / md_cases)
# ─────────────────────────────────────────────────────────────
_ANALYZE_PROMPT = (
    "วิเคราะห์สไลด์นี้ ตอบกลับเป็น markdown ภาษาไทยเท่านั้น อธิบายให้ครบหัวข้อ:\n"
    "- หัวข้อสไลด์ (Slide title)\n"
    "- วัตถุประสงค์ (Purpose)\n"
    "- อุปกรณ์/เครื่องจักรที่เกี่ยวข้อง (Equipment)\n"
    "- ขั้นตอน/กระบวนการ (Process flow)\n"
    "- ข้อสังเกตสำคัญ (Important observations)\n"
    "- สาเหตุ (Root cause)\n"
    "- วิธีแก้/มาตรการ (Countermeasure)\n"
    "ถ้าสไลด์ไม่มีข้อมูลบางหัวข้อ ให้ข้ามหัวข้อนั้นได้"
)

_SUMMARY_PROMPT = (
    "สรุปเนื้อหา KM ต่อไปนี้ให้กระชับเป็นภาษาไทย ให้คงหัวข้อสำคัญ ตัวเลข/สถานะที่สำคัญ "
    "และข้อสรุปหลักไว้ เพื่อใช้เป็นบทสรุปย่อสำหรับการค้นหาและตอบคำถามอย่างรวดเร็ว "
    "ตอบกลับเป็น markdown เท่านั้น ห้ามเพิ่มข้อความอื่นนอกเหนือจากบทสรุป"
)

_CASES_PROMPT = (
    "คุณเป็นผู้ช่วยแยกบันทึกการประชุม morning talk ของฝ่ายซ่อมบำรุงให้เป็นเคสความรู้ "
    "อ่านเนื้อหา Slide Analysis ที่ให้แล้วแตกเป็นหลายเคส โดย 1 เคส คือ 1 ปัญหา "
    "และรวมข้อมูลของปัญหาเดียวกันที่กระจายอยู่หลายสไลด์เข้าเป็นเคสเดียว "
    "ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON เป็น object เดียวที่มี key ชื่อ cases "
    "เป็น array ของ object โดยแต่ละ object มี key ดังนี้: "
    "symptom cause solution result machine component category severity tags "
    "ทั้งหมดเป็นภาษาไทยยกเว้นชื่อเครื่องหรือชิ้นส่วนที่เป็นภาษาอังกฤษได้ "
    "ค่า category ให้เลือกจาก safety mechanical electrical process quality other "
    "และ severity ให้เลือกจาก low medium high "
    "ถ้าไม่มีข้อมูล result ให้ใส่คำว่า ไม่ทราบผลลัพธ์ "
    "ส่วน machine และ component ถ้าไม่มีให้ใส่ค่าว่าง "
    "และ tags เป็น array 2 ถึง 4 คำภาษาอังกฤษ"
)


def _azure_ready():
    import rag
    return rag.AZURE_READY


def analyze_slide(png_path, model=None):
    """ส่งรูปสไลด์ 1 หน้าเข้า Azure vision -> markdown วิเคราะห์ (ไทย)
    Azure ไม่พร้อม/ต่อไม่ได้ -> คืน mock (ขึ้นต้น [MOCK]) ให้ UI เดินต่อได้"""
    import rag
    if not rag.AZURE_READY:
        return f"[MOCK — ยังไม่ได้ตั้งค่า Azure vision] วิเคราะห์ {Path(png_path).name} ไม่ได้"
    try:
        data = Path(png_path).read_bytes()
        b64 = base64.b64encode(data).decode()
        deployment = rag._azure_deployment(model or "") if model else rag.AZURE_DEPLOYMENT
        resp = rag._get_azure_client().chat.completions.create(
            model=deployment,
            temperature=0.2,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": _ANALYZE_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[KM] analyze_slide ล้มเหลว ({type(e).__name__}: {e}) -> mock")
        return f"[MOCK — วิเคราะห์ไม่สำเร็จ: {type(e).__name__}] {Path(png_path).name}"


def summarize(analysis_text, model=None):
    """สรุปผลวิเคราะห์ทุกหน้า -> บทสรุปย่อไทย. ใช้ lane เดียวกับ rag (_llm_chat) — Azure/local ก็ได้
    ล้มเหลว -> คืน mock"""
    import rag
    use_model = (model or "").strip() or rag.default_model()
    try:
        return rag._llm_chat(
            [{"role": "system", "content": _SUMMARY_PROMPT},
             {"role": "user", "content": analysis_text}],
            use_model)
    except Exception as e:
        print(f"[KM] summarize ล้มเหลว ({type(e).__name__}: {e}) -> mock")
        head = (analysis_text or "").strip().splitlines()
        return "[MOCK — สรุปไม่สำเร็จ]\n" + "\n".join(head[:8])


def extract_cases(analysis_text, model=None):
    """แตกผลวิเคราะห์ (Morning Talk) เป็นเคส -> list[dict] field ของ jarvis case
    (symptom/cause/solution/result/machine/component/category/severity/tags)
    ล้มเหลว/parse ไม่ได้ -> คืน [] (ไม่สร้างเคสมั่ว)"""
    import rag
    use_model = (model or "").strip() or rag.default_model()
    try:
        out = rag._llm_chat(
            [{"role": "system", "content": _CASES_PROMPT},
             {"role": "user", "content": f"ต่อไปนี้คือเนื้อหา Slide Analysis:\n{analysis_text}"}],
            use_model)
        cases = _parse_cases_json(out)
        # กรองเคสว่าง (ไม่มีอาการเลย = โมเดลเดามั่ว) ออก
        return [c for c in cases if (c.get("symptom") or "").strip()]
    except Exception as e:
        print(f"[KM] extract_cases ล้มเหลว ({type(e).__name__}: {e}) -> []")
        return []


def _parse_cases_json(text):
    """ดึง JSON {cases:[...]} จากคำตอบ LLM (เผื่อห่อด้วย ```json ... ``` หรือมีข้อความปน)"""
    s = (text or "").strip()
    # ตัดรั้ว code fence ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    # เผื่อมีข้อความนำ/ตาม — คว้า object นอกสุด
    if not s.startswith("{"):
        b = s.find("{")
        e = s.rfind("}")
        if b != -1 and e != -1:
            s = s[b:e + 1]
    data = json.loads(s)
    cases = data.get("cases") if isinstance(data, dict) else data
    return cases if isinstance(cases, list) else []
