"""
เขียนผล .md ลง Obsidian vault เดิม (ทาง A: subfolder ใน vault ที่มี standard work อยู่แล้ว)
โครง:
    <VAULT_PATH>/meetings/<meeting_id>.md   ไฟล์ประชุม (1 ประชุม = 1 ไฟล์ ไม่ทับกัน)
    <VAULT_PATH>/machines/machine-X.md      ไฟล์เครื่องจักร (สร้างถ้ายังไม่มี + append ประวัติ)
"""
import os
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
