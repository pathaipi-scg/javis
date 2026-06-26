# 01 — STACK (เครื่องมือที่ใช้)

ระบบ: ประชุม → ข้อความ → MSSQL → AI → `.md` → Obsidian (ค้นหาได้)

| ขั้น | หน้าที่ | เครื่องมือ |
|------|---------|-----------|
| Input | รับเสียงประชุม + รูปภาพ(พร้อม caption) | ฟอร์มเว็บ / upload |
| เก็บเสียง | อัดประชุม | Teams Record / มือถือ / อัดจอ |
| รับไฟล์ | trigger งาน | Django + watchdog / upload / Graph webhook |
| แยกเสียง | แปลงฟอร์แมต | ffmpeg → 16kHz mono wav |
| STT | เสียง→ข้อความ + แยกคนพูด | WhisperX (whisper + VAD + diarization) |
| คิวงาน | ทำเบื้องหลัง | Django-Q2 (คิวอยู่บน MSSQL — ไม่ต้องลง Redis) |
| Database | source of truth | MS SQL Server + Full-Text Search |
| AI | ดึง JSON เครื่องจักร | Qwen3 (รันบน server ภายในองค์กร, OpenAI-compatible API) |
| Output | เขียนไฟล์ความรู้ | Markdown + YAML frontmatter |
| View/Search | ดู/ค้น/กราฟ | Obsidian + Dataview plugin |
| Search (option) | ค้นผ่านแชท | Teams Bot (Django REST) |

## ตัวเลือกที่ตัดสินแล้ว
- **DB**: MS SQL Server (org มีอยู่, multi-user, security ตามบริษัท)
- **Backend**: Django (admin ฟรี, ORM, REST, migration)
- **LLM**: Qwen3 — รันบน server ภายในองค์กรอยู่แล้ว ข้อมูลไม่ออกนอกองค์กรเลย ฟรี (เรียกผ่าน OpenAI-compatible API: vLLM/Ollama)
- **Input**: รับ 2 อย่าง — (1) ไฟล์เสียงประชุม (2) รูปภาพ + caption ใต้รูป เช่น รูปมอเตอร์ + "มอเตอร์เสีย"
- **STT**: ทำเอง WhisperX (ไม่พึ่ง Teams transcript ที่ต้องขอ permission)
- **คิวงาน**: Django-Q2 — ลงแค่ `pip install django-q2` ใช้ MSSQL เป็น broker ไม่ต้องลง Redis/Celery หรือโปรแกรม server แยก
