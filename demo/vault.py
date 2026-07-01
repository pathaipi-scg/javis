"""
เขียนผล .md ลง Obsidian vault เดิม (ทาง A: subfolder ใน vault ที่มี standard work อยู่แล้ว)
โครง:
    <VAULT_PATH>/meetings/<meeting_id>.md   ไฟล์ประชุม (1 ประชุม = 1 ไฟล์ ไม่ทับกัน)
    <VAULT_PATH>/machines/machine-X.md      ไฟล์เครื่องจักร (สร้างถ้ายังไม่มี + append ประวัติ)
"""
import os
import re
import shutil
from pathlib import Path


VAULT_PATH = os.getenv("VAULT_PATH", "")


def _unique_meeting_id(meetings_dir, date):
    """กันชื่อชน: ประชุมแรกของวัน = <date>, ตัวถัดไป = <date>-2, -3 ...
    คืน id ที่ยังไม่มีไฟล์ → รับประกัน 1 ประชุม 1 ไฟล์ ไม่ทับของเดิม"""
    if not (meetings_dir / f"{date}.md").exists():
        return date
    n = 2
    while (meetings_dir / f"{date}-{n}.md").exists():
        n += 1
    return f"{date}-{n}"


def save_to_vault(markdown, machines, date, when=None, image_src=None, image_name=None):
    """คืนข้อความสรุปว่าเขียนไฟล์อะไรไปบ้าง (หรือ error ถ้า path ไม่ถูก)
    when      = วันที่+เวลาที่บันทึก (YYYY-MM-DD HH:MM) ใช้ลงคอลัมน์ 'บันทึกเมื่อ'
    image_src = path รูปชั่วคราว (จะ copy เข้า attachments/ ให้ Obsidian เห็น)"""
    import datetime as _dt
    when = when or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not VAULT_PATH:
        return "⚠️ ยังไม่ได้ตั้ง VAULT_PATH ใน .env"
    vault = Path(VAULT_PATH)
    if not vault.exists():
        return f"⚠️ ไม่พบ vault: {VAULT_PATH} — ตรวจ path ใน .env"

    meetings = vault / "meetings"
    machines_dir = vault / "machines"
    meetings.mkdir(exist_ok=True)
    machines_dir.mkdir(exist_ok=True)

    written = []

    # 1) ไฟล์ประชุม — ชื่อ unique กันทับ (1 ประชุม = 1 ไฟล์)
    meeting_id = _unique_meeting_id(meetings, date)
    mfile = meetings / f"{meeting_id}.md"
    mfile.write_text(markdown, encoding="utf-8")
    written.append(f"meetings/{meeting_id}.md")

    # 1.5) copy รูปเข้า attachments/ (Obsidian หา ![[ชื่อรูป]] เจอทั้ง vault)
    if image_src and image_name and Path(image_src).exists():
        att = vault / "attachments"
        att.mkdir(exist_ok=True)
        shutil.copy(image_src, att / image_name)
        written.append(f"attachments/{image_name}")

    # 2) ไฟล์เครื่องจักร — สร้างถ้ายังไม่มี แล้ว append แถวประวัติ
    for m in machines:
        name = m.get("machine", "?")
        f = machines_dir / f"machine-{name}.md"
        if not f.exists():
            header = (
                f"---\n"
                f"machine: {name}\n"
                f"location: {m.get('location','')}\n"
                f"last_repair: {m.get('repair_date','')}\n"
                f"status: เสีย\n"
                f"---\n"
                f"# เครื่อง {name}\n\n"
                f"## ประวัติซ่อม\n"
                f"| วันที่ซ่อม | อาการ | จุด | action | บันทึกเมื่อ | ที่มา |\n"
                f"|-----------|-------|-----|--------|-----------|-------|\n"
            )
            f.write_text(header, encoding="utf-8")

        row = (
            f"| {m.get('repair_date','')} | {m.get('issue','')} | "
            f"{m.get('location','')} | {m.get('action','')} | {when} | [[{meeting_id}]] |\n"
        )
        with f.open("a", encoding="utf-8") as fh:
            fh.write(row)
        written.append(f"machines/machine-{name}.md")

    return "✅ เขียนแล้ว: " + ", ".join(written)


# ─────────────────────────────────────────────────────────────
# tag-first: เขียนเคส 1 ไฟล์ลง cases/<case_id>.md ตามสเปก PIPELINE.html
# (ผู้ใช้กรอก field เอง — แม่นกว่าให้ AI สกัด)
# ─────────────────────────────────────────────────────────────

def _safe(name):
    """แปลงเป็นชื่อโฟลเดอร์ที่ปลอดภัย (กันอักขระต้องห้ามบน Windows/Obsidian)
    ว่าง -> _unsorted เพื่อไม่ให้เคสหล่นหาย"""
    name = (name or "").strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)   # อักขระที่ Windows ห้ามใช้ในชื่อไฟล์
    name = name.strip(". ")                       # กันจุด/ช่องว่างท้ายชื่อ (Windows ตัดทิ้ง)
    return name or "_unsorted"


def _existing_or(parent, name):
    """ถ้ามีโฟลเดอร์ชื่อตรงกันอยู่แล้ว (ไม่สนพิมพ์เล็ก/ใหญ่) ใช้ตัวเดิม
    กันเคสเดียวกันแตกเป็นสองโฟลเดอร์ เช่น production / Production"""
    if parent.exists():
        for d in parent.iterdir():
            if d.is_dir() and d.name.casefold() == name.casefold():
                return d
    return parent / name


def _next_case_id(cases_root, year):
    """รหัสเคสถัดไป MTN-<ปี>-<NNNN> (4 หลัก) ไม่ชนของเดิม
    สแกนทุกชั้นย่อย (rglob) เพราะเคสกระจายอยู่ใน cases/<plant>/<dept>/"""
    n = 0
    for f in cases_root.rglob(f"MTN-{year}-*.md"):
        m = re.search(rf"MTN-{year}-(\d+)", f.stem)
        if m:
            n = max(n, int(m.group(1)))
    return f"MTN-{year}-{n + 1:04d}"


def save_case(fields, image_src=None, image_name=None):
    """เขียนเคสตามสเปก -> cases/<case_id>.md (frontmatter + 4 หัวข้อ)
    fields: machine, component, plant, line, source, category, severity, status,
            downtime_min, parts_used, tags(list), symptom, cause, solution, result, caption
    คืน (ข้อความสรุป, case_id)"""
    import datetime as _dt
    if not VAULT_PATH:
        return "⚠️ ยังไม่ได้ตั้ง VAULT_PATH ใน .env", None
    vault = Path(VAULT_PATH)
    if not vault.exists():
        return f"⚠️ ไม่พบ vault: {VAULT_PATH} — ตรวจ path ใน .env", None

    # โครงชั้น: cases/<โรงงาน>/<ฝ่าย>/<case_id>.md  (เช่น cases/A/production/MTN-2026-0001.md)
    cases_root = vault / "cases"
    plant_dir = _existing_or(cases_root, _safe(fields.get("plant")))
    case_dir = _existing_or(plant_dir, _safe(fields.get("department")))
    case_dir.mkdir(parents=True, exist_ok=True)
    plant, dept = plant_dir.name, case_dir.name   # ชื่อโฟลเดอร์จริงที่ใช้ (อาจเป็นตัวเดิมที่มีอยู่)
    now = _dt.datetime.now()
    today = now.strftime("%Y-%m-%d")
    case_id = _next_case_id(cases_root, now.year)   # นับข้ามทุกชั้นให้เลขไม่ชน
    tags = fields.get("tags") or []

    lines = [
        "---",
        f"case_id: {case_id}",
        f"date: {today}",
        f"source: {fields.get('source', '')}",
        f"plant: {plant}",
        f"department: {dept}",
        f"line: {fields.get('line', '')}",
        f"machine: {fields.get('machine', '')}",
        f"component: {fields.get('component', '')}",
        f"category: {fields.get('category', '')}",
        f"severity: {fields.get('severity', '')}",
        f"status: {fields.get('status', '')}",
        f"downtime_min: {fields.get('downtime_min') or 0}",
        f"parts_used: {fields.get('parts_used', '')}",
        f"tags: [{', '.join(tags)}]",
        "---",
        "",
        "# อาการ (Symptom)",
        (fields.get("symptom", "") or "").strip(),
        "",
        "# สาเหตุ (Root cause)",
        (fields.get("cause", "") or "").strip(),
        "",
        "# วิธีแก้ (Solution)",
        (fields.get("solution", "") or "").strip(),
        "",
        "# ผลลัพธ์ (Result)",
        (fields.get("result", "") or "").strip(),
    ]
    if image_name:
        lines += ["", "# รูปประกอบ", f"![[{image_name}]]"]   # แค่แนบ ไม่วิเคราะห์
        cap = (fields.get("caption", "") or "").strip()
        if cap:
            lines.append(f"> {cap}")

    cfile = case_dir / f"{case_id}.md"
    cfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written = [f"cases/{plant}/{dept}/{case_id}.md"]

    if image_src and image_name and Path(image_src).exists():
        att = vault / "attachments"
        att.mkdir(exist_ok=True)
        shutil.copy(image_src, att / image_name)
        written.append(f"attachments/{image_name}")

    return "✅ บันทึกเคส " + case_id + " → " + ", ".join(written), case_id
