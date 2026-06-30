# 07 — ARCHITECTURE (สถาปัตยกรรมรวม)

```
[เก็บเสียง — ตอนประชุม]              [แอป Django — รัน server ตลอด]
Teams / มือถือ / อัดจอ  ──ไฟล์──▶  inbox ──▶ Django-Q2 (คิวบน MSSQL)
                                              │
                  ┌───────────────────────────┼──────────────────┐
                  ▼            ▼               ▼                  ▼
               ffmpeg → WhisperX       Typhoon (server)      MSSQL (ORM)
              (เสียง→ข้อความ+คน)        (ดึง JSON)          (source of truth)
                                                                  │
                                                                  ▼
                                                       เขียน .md → Obsidian vault
                                                                  │
                                  ┌───────────────────────────────┤
                                  ▼                               ▼
                       Obsidian + Dataview + Graph        Teams Bot (ค้นผ่านแชท)
```

## Flow ย่อ (infographic แนวนอน)
```
เสียง+รูป 🎙️🖼️ → WhisperX → MSSQL 🗄️ → Typhoon 🤖 → .md 📄 → Obsidian 🔍
```

## จุดเด่น
- **อัตโนมัติ** — ประชุมจบ ระบบทำงานเอง
- **MS stack เดียว** — Teams + SQL + Azure อยู่ tenant บริษัท
- **ข้อมูลปลอดภัย** — ไม่ออกนอกองค์กร
- **STT ทำเอง** — ไม่ติด permission ของ Teams transcript
- **ค้นไว + เห็นกราฟ** — Obsidian โยงเครื่องจักร ↔ ประชุม
