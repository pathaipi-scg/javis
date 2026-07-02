# Meeting → Knowledge Base — เอกสารออกแบบ

ระบบแปลงเสียงประชุม → ข้อความ → MSSQL → AI ดึงข้อมูลเครื่องจักร → `.md` ใน Obsidian → ค้นหาได้

## สารบัญ (เอาไปทำ Canva ทีละไฟล์)
| ไฟล์ | เนื้อหา |
|------|---------|
| [01-stack.md](01-stack.md) | เครื่องมือที่ใช้ + ตัวเลือกที่ตัดสินแล้ว |
| [02-file-plan.md](02-file-plan.md) | โครงโปรเจกต์ Django |
| [03-pipeline.md](03-pipeline.md) | เส้นทางข้อมูล 11 ขั้น |
| [04-workflow.md](04-workflow.md) | มุมคนใช้งาน + เก็บเสียง vs แปลง |
| [05-example.md](05-example.md) | ตัวอย่างจริงแต่ละขั้น (synthetic) |
| [06-obsidian-visualize.md](06-obsidian-visualize.md) | ภาพที่เห็นบน Obsidian (3 มุม) |
| [07-architecture.md](07-architecture.md) | สถาปัตยกรรมรวม + จุดเด่น |

## สรุป stack
เสียง+รูป → WhisperX → MSSQL → Typhoon2 8B (server ภายใน) → Markdown → Obsidian + Dataview
Backend: Django + Django-Q2 (คิวบน MSSQL — ไม่ต้องลง Redis/Celery)

## Demo เว็บ
โฟลเดอร์ [../demo/](../demo/) — Flask app ลองดู pipeline ได้เลย (`python demo/app.py`)
