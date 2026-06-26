# 03 — PIPELINE (เส้นทางข้อมูล)

```
①  Input (2 แบบ — ใช้แยกหรือพร้อมกัน)
    A. ไฟล์เสียงประชุม (Teams Record / มือถือ / อัดจอ)
    B. รูปภาพ + caption ใต้รูป (เช่น รูปมอเตอร์ + "มอเตอร์เสีย")
            ↓
②  ไฟล์เข้า media/inbox/
    upload หน้าเว็บ  |  watchdog จับ  |  Graph ดึง .mp4
            ↓
③  Django-Q2 task เริ่ม (คิวอยู่บน MSSQL, รัน `python manage.py qcluster`)
            ↓
④  ffmpeg → 16kHz mono wav
            ↓
⑤  WhisperX
    - transcribe (ไทย)
    - VAD ตัดท่อน/ความเงียบ
    - diarization แยก SPEAKER_00/01/02
            ↓
⑥  map SPEAKER → ชื่อจริง
    (ครั้งแรก map เอง / ครั้งถัดไป voice fingerprint จำเสียง)
            ↓
⑦  เก็บ MSSQL (Meeting.raw_text + Full-Text index)
            ↓
⑧  Qwen3 (server ภายใน) → JSON
    รวม transcript + caption รูป เป็น context เดียว ป้อน Qwen3
    {summary, machines:[{machine, issue, location, repair_date, action}]}
            ↓
⑨  เก็บ MachineEvent (structured) ลง MSSQL
            ↓
⑩  render .md → vault/
    - meetings/2026-06-25.md  (สรุปประชุม)
    - machines/machine-A.md   (append ประวัติ)
            ↓
⑪  ค้นหา: Obsidian Dataview  |  Teams Bot
```

## หมายเหตุแต่ละขั้น
- **②**: 3 ทางเข้าได้หมด — เลือกใช้ทางใดทางหนึ่งหรือหลายทาง
- **⑤**: ใช้ GPU จะเร็ว (ประชุม 1 ชม. ≈ 2–5 นาที); CPU ช้ามาก
- **⑥**: ทำครั้งเดียวต่อคน ระบบจำเสียงไว้ครั้งถัดไป
- **⑦**: MSSQL = source of truth — ไฟล์ .md regenerate ใหม่ได้เสมอ
```
