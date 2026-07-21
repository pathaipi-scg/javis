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


def _parse_fm(md):
    """ดึง frontmatter (ระหว่าง --- คู่แรก) จากเนื้อ .md เป็น dict อย่างง่าย"""
    m = re.match(r"^---\s*\n(.*?)\n---", md, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    return fm


def render_case(fields):
    """สร้างเนื้อ .md ของเคส (ยังไม่เขียนลงดิสก์) -> (case_id, markdown)
    ใช้ทำหน้าพรีวิวก่อนบันทึก — คำนวณ case_id + ชื่อโฟลเดอร์ canonical ให้ตรงกับตอนเซฟจริง
    fields: machine, component, plant, department, line, source, category, severity,
            status, downtime_min, parts_used, tags(list), symptom, cause, solution, result, caption"""
    import datetime as _dt
    now = _dt.datetime.now()
    today = now.strftime("%Y-%m-%d")
    plant = _safe(fields.get("plant"))
    dept = _safe(fields.get("department"))
    case_id = f"MTN-{now.year}-0001"
    vault = Path(VAULT_PATH) if VAULT_PATH else None
    if vault and vault.exists():
        cases_root = vault / "cases"
        plant = _existing_or(cases_root, plant).name         # ใช้ชื่อโฟลเดอร์เดิมถ้ามี (กันซ้ำ)
        dept = _existing_or(cases_root / plant, dept).name
        case_id = _next_case_id(cases_root, now.year)         # นับข้ามทุกชั้นให้เลขไม่ชน
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
    if image_name := fields.get("image_name"):
        lines += ["", "# รูปประกอบ", f"![[{image_name}]]"]   # แค่แนบ ไม่วิเคราะห์
        cap = (fields.get("caption", "") or "").strip()
        if cap:
            lines.append(f"> {cap}")

    return case_id, "\n".join(lines) + "\n"


def save_markdown(md, image_src=None, image_name=None):
    """เขียนเนื้อ .md (ที่อาจถูกแก้ในหน้าพรีวิว) ลง vault
    อ่าน plant/department/case_id จาก frontmatter เพื่อจัดโฟลเดอร์ให้ถูก -> คืน (สรุป, case_id)"""
    import datetime as _dt
    if not VAULT_PATH:
        return "⚠️ ยังไม่ได้ตั้ง VAULT_PATH ใน .env", None
    vault = Path(VAULT_PATH)
    if not vault.exists():
        return f"⚠️ ไม่พบ vault: {VAULT_PATH} — ตรวจ path ใน .env", None

    fm = _parse_fm(md)
    cases_root = vault / "cases"
    plant_dir = _existing_or(cases_root, _safe(fm.get("plant")))
    case_dir = _existing_or(plant_dir, _safe(fm.get("department")))
    case_dir.mkdir(parents=True, exist_ok=True)
    plant, dept = plant_dir.name, case_dir.name
    case_id = fm.get("case_id") or _next_case_id(cases_root, _dt.datetime.now().year)

    cfile = case_dir / f"{case_id}.md"
    cfile.write_text(md if md.endswith("\n") else md + "\n", encoding="utf-8")
    written = [f"cases/{plant}/{dept}/{case_id}.md"]

    if image_src and image_name and Path(image_src).exists():
        att = vault / "attachments"
        att.mkdir(exist_ok=True)
        shutil.copy(image_src, att / image_name)
        written.append(f"attachments/{image_name}")

    return "✅ บันทึกเคส " + case_id + " → " + ", ".join(written), case_id


def save_case(fields, image_src=None, image_name=None):
    """เซฟเคสจาก fields ตรงๆ (render แล้วเขียนทันที) — คงไว้ใช้เรียกแบบไม่ผ่านพรีวิว"""
    if not VAULT_PATH:
        return "⚠️ ยังไม่ได้ตั้ง VAULT_PATH ใน .env", None
    if image_name:
        fields = {**fields, "image_name": image_name}
    _, md = render_case(fields)
    return save_markdown(md, image_src=image_src, image_name=image_name)


# ─────────────────────────────────────────────────────────────
# KM (Knowledge Management) — อัปโหลดเอกสาร -> PNG -> summary
# โครงในโฟลเดอร์ที่เลือก (mirror scg-km-webchat):
#     <VAULT>/<target>/<source_file>            ไฟล์ดิบ
#     <VAULT>/<target>/KM_YYYYMMDD_HHMMSS.md     metadata (frontmatter)
#     <VAULT>/<target>/KM_YYYYMMDD_HHMMSS/       asset folder (SlideNNN.png)
#     <VAULT>/<target>/KM_YYYYMMDD_HHMMSS_summary.md  บทสรุป (หลัง train)
# ─────────────────────────────────────────────────────────────
_KM_IGNORE_DIRS = {".obsidian", "attachments", ".trash", ".git"}


def _vault_join(rel):
    """รวม path ย่อยกับ vault อย่างปลอดภัย (กัน ../ หลุดออกนอก vault) -> Path สัมบูรณ์"""
    vault = Path(VAULT_PATH).resolve()
    p = (vault / (rel or "")).resolve()
    if p != vault and vault not in p.parents:
        raise ValueError("path อยู่นอก vault")
    return p


def list_vault_tree():
    """โครงโฟลเดอร์ใน vault (สำหรับ browser เลือกที่เก็บ) — ข้ามโฟลเดอร์ระบบ + asset KM_*
    คืน list ของ node {name, path(rel), children?}"""
    if not VAULT_PATH or not Path(VAULT_PATH).exists():
        return []

    def walk(d, rel):
        nodes = []
        for entry in sorted(d.iterdir(), key=lambda e: e.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name in _KM_IGNORE_DIRS or entry.name.startswith("KM_"):
                continue
            crel = f"{rel}/{entry.name}" if rel else entry.name
            node = {"name": entry.name, "path": crel}
            children = walk(entry, crel)
            if children:
                node["children"] = children
            nodes.append(node)
        return nodes

    return walk(Path(VAULT_PATH), "")


def make_folder(rel):
    """สร้างโฟลเดอร์ใหม่ใน vault (สำหรับปุ่ม 'เพิ่มโฟลเดอร์' ใน tree). คืน path rel ที่สร้าง"""
    if not VAULT_PATH:
        raise ValueError("ยังไม่ได้ตั้ง VAULT_PATH")
    p = _vault_join(rel)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.relative_to(Path(VAULT_PATH).resolve())).replace("\\", "/")


def _km_id(when):
    return "KM_" + when.strftime("%Y%m%d_%H%M%S")


def _km_meta_text(o):
    """สร้าง metadata (frontmatter) ของ KM doc — อ่านกลับด้วย _parse_fm ได้"""
    lines = [
        "---",
        f"KM_ID: {o['km_id']}",
        f"Source_File: {o['source_file']}",
        f"Target_Path: {o['target']}",
        f"Category: {o.get('category', '')}",
        f"Machine: {o.get('machine', '')}",
        f"Processing_Status: {o.get('processing_status', 'Uploaded')}",
        f"PNG_Count: {o.get('png_count', 0)}",
        f"Asset_Folder: {o['km_id']}",
        f"Created: {o['created']}",
        f"Training_Status: {o.get('training_status', 'NotTrained')}",
        f"Training_Date: {o.get('training_date', '')}",
        "---",
        "",
    ]
    return "\n".join(lines)


def save_km_upload(target, src_path, filename, category="", machine=""):
    """เขียนไฟล์ดิบ + metadata + asset folder ลง vault. คืน dict
    {km_id, target, folder(rel), meta_rel, asset_rel} หรือ raise ถ้า VAULT ไม่พร้อม"""
    import datetime as _dt
    if not VAULT_PATH or not Path(VAULT_PATH).exists():
        raise ValueError(f"ไม่พบ vault: {VAULT_PATH} — ตรวจ VAULT_PATH ใน .env")
    now = _dt.datetime.now()
    km_id = _km_id(now)
    dest = _vault_join(target)
    dest.mkdir(parents=True, exist_ok=True)

    # 1) ไฟล์ดิบ
    raw = dest / filename
    if str(Path(src_path).resolve()) != str(raw.resolve()):
        shutil.copy(src_path, raw)

    # 2) asset folder
    asset = dest / km_id
    asset.mkdir(exist_ok=True)

    # 3) metadata
    meta = dest / f"{km_id}.md"
    meta.write_text(_km_meta_text({
        "km_id": km_id, "source_file": filename, "target": target,
        "category": category, "machine": machine,
        "created": now.strftime("%Y-%m-%d %H:%M"),
    }), encoding="utf-8")

    vroot = Path(VAULT_PATH).resolve()
    rel = lambda p: str(p.resolve().relative_to(vroot)).replace("\\", "/")
    return {"km_id": km_id, "target": target, "folder": rel(dest),
            "meta_rel": rel(meta), "asset_rel": rel(asset)}


def _replace_fm_field(md, key, value):
    """แทนค่า field ใน frontmatter (key: value) — ใช้อัปเดตสถานะ KM"""
    pat = re.compile(rf"(?m)^({re.escape(key)}:).*$")
    if pat.search(md):
        return pat.sub(rf"\1 {value}", md, count=1)
    return md


def set_km_converted(meta_rel, km_id, png_count):
    """อัปเดต metadata หลังแปลง PNG เสร็จ: Processing_Status=Converted + PNG_Count + ฝัง ![[...]]"""
    meta = _vault_join(meta_rel)
    md = meta.read_text(encoding="utf-8")
    md = _replace_fm_field(md, "Processing_Status", "Converted")
    md = _replace_fm_field(md, "PNG_Count", str(png_count))
    if png_count > 0 and "# Slides" not in md:
        md = md.rstrip() + "\n\n# Slides\n" + "".join(
            f"![[{km_id}/Slide{i:03d}.png]]\n\n" for i in range(1, png_count + 1))
    meta.write_text(md, encoding="utf-8")


def set_km_trained(meta_rel, analysis_md, slide_count):
    """อัปเดต metadata หลัง train: Training_Status=Trained + Training_Date + append # Slide Analysis"""
    import datetime as _dt
    meta = _vault_join(meta_rel)
    md = meta.read_text(encoding="utf-8")
    md = _replace_fm_field(md, "Training_Status", "Trained")
    md = _replace_fm_field(md, "Training_Date", _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    # ตัด Slide Analysis เดิม (ถ้าเทรนซ้ำ) ก่อน append ใหม่
    md = re.sub(r"\n# Slide Analysis\b.*$", "", md, flags=re.S).rstrip()
    md += "\n\n# Slide Analysis\n" + (analysis_md or "").strip() + "\n"
    meta.write_text(md, encoding="utf-8")


def save_km_summary(folder_rel, km_id, summary_md, category="", source_file=""):
    """เขียน <km_id>_summary.md (บทสรุปย่อ) พร้อม frontmatter ให้ rag.load_km_docs อ่านได้
    คืน path rel ของไฟล์สรุป"""
    folder = _vault_join(folder_rel)
    folder.mkdir(parents=True, exist_ok=True)
    head = (
        "---\n"
        f"KM_ID: {km_id}\n"
        f"Category: {category}\n"
        f"Source_File: {source_file}\n"
        "---\n\n"
    )
    f = folder / f"{km_id}_summary.md"
    f.write_text(head + (summary_md or "").strip() + "\n", encoding="utf-8")
    vroot = Path(VAULT_PATH).resolve()
    return str(f.resolve().relative_to(vroot)).replace("\\", "/")


def find_km_docs():
    """สแกน vault หา KM doc ทั้งหมด (ไฟล์ KM_*.md ที่ไม่ใช่ _summary) -> list[dict] สถานะ
    ใช้ทำรายการในหน้า KM + หา not-trained"""
    if not VAULT_PATH or not Path(VAULT_PATH).exists():
        return []
    vroot = Path(VAULT_PATH).resolve()
    docs = []
    for f in sorted(vroot.rglob("KM_*.md")):
        if f.name.endswith("_summary.md"):
            continue
        try:
            fm = _parse_fm(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not fm.get("KM_ID"):
            continue
        folder = f.parent
        docs.append({
            "km_id": fm.get("KM_ID"),
            "source_file": fm.get("Source_File", ""),
            "category": fm.get("Category", ""),
            "machine": fm.get("Machine", ""),
            "processing_status": fm.get("Processing_Status", ""),
            "training_status": fm.get("Training_Status", "NotTrained"),
            "png_count": int(re.sub(r"\D", "", fm.get("PNG_Count", "0")) or 0),
            "target": fm.get("Target_Path", ""),
            "folder": str(folder.resolve().relative_to(vroot)).replace("\\", "/"),
            "meta_rel": str(f.resolve().relative_to(vroot)).replace("\\", "/"),
        })
    return docs
