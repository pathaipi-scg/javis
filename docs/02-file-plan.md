# 02 — FILE PLAN (โครงโปรเจกต์)

```
jarvis/
├── manage.py
├── requirements.txt
├── config/
│   ├── settings.py            # MSSQL, Celery, Azure keys
│   ├── celery.py
│   └── urls.py
├── ingest/                    # รับไฟล์เข้า
│   ├── views.py               # upload endpoint + Teams webhook
│   ├── watcher.py             # watchdog จับไฟล์ใหม่ในโฟลเดอร์
│   └── graph.py               # ดึง .mp4 recording จาก Teams (Graph API)
├── pipeline/                  # หัวใจ
│   ├── audio.py               # ffmpeg แปลงเสียง
│   ├── transcribe.py          # WhisperX → ข้อความ + ชื่อคน + เวลา
│   ├── extract.py             # Azure OpenAI → JSON เครื่องจักร
│   ├── render.py              # เขียน .md ลง Obsidian vault
│   └── tasks.py               # Django-Q2 task orchestration
├── core/
│   ├── models.py              # Meeting, MachineEvent, Speaker
│   └── admin.py               # หน้า admin ดู/แก้ข้อมูล
├── vault/                     # Obsidian vault (output)
│   ├── meetings/              # 1 ไฟล์/ประชุม
│   ├── machines/              # 1 ไฟล์/เครื่องจักร (สะสมประวัติ)
│   └── dashboard.md           # Dataview query รวม
└── media/
    ├── inbox/                 # ไฟล์เสียงเข้ามาตรงนี้
    └── processed/             # ย้ายมาเมื่อทำเสร็จ
```

## หน้าที่ไฟล์สำคัญ
| ไฟล์ | ทำอะไร |
|------|--------|
| `ingest/views.py` | รับไฟล์ upload + รับ webhook Teams → โยนเข้าคิว Django-Q2 |
| `pipeline/transcribe.py` | รับ .wav → คืน transcript (ข้อความ+คน+เวลา) |
| `pipeline/extract.py` | รับ transcript → คืน JSON เครื่องจักร |
| `pipeline/render.py` | รับ JSON → เขียน meetings/*.md + machines/*.md |
| `core/models.py` | ตาราง MSSQL: Meeting, MachineEvent, Speaker |
