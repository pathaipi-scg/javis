# Demo เว็บ — Meeting → Knowledge Base

หน้าเว็บง่ายๆ ให้ลองดู pipeline: รับ **ไฟล์เสียงประชุม** + **รูปภาพพร้อม caption** → ถอดข้อความ → **LLM (ปัจจุบันใช้ Typhoon2 8B)** ดึงข้อมูลเครื่องจักร → พรีวิวไฟล์ `.md` แบบที่จะลง Obsidian

## รัน

```bash
pip install -r requirements.txt
python app.py
```
เปิด http://127.0.0.1:5000

> ยังไม่ต้องต่อ LLM/whisper ก็รันได้ — จะขึ้นข้อมูล **mock** ให้เห็น UI ก่อน
> พอต่อ server จริง (ตั้งค่าข้างล่าง) ผลจะมาจาก LLM จริง

## ต่อ server LLM ของคุณ (ปัจจุบันใช้ Typhoon2 8B)

> ชื่อตัวแปรยังเป็น `QWEN_*` (ของเดิมตั้งแต่ใช้ Qwen3-VL) แต่ใส่โมเดลอะไรก็ได้ที่เสิร์ฟแบบ OpenAI-compatible

แก้ที่หัวไฟล์ `llm.py` หรือตั้ง env ก่อนรัน:

```bash
# ปัจจุบัน: Typhoon2 8B บน Ollama (ไทยเก่งกว่า, ไม่ต้องมองรูป)
set QWEN_BASE_URL=http://<server-ip>:11434/v1
set QWEN_MODEL=scb10x/llama3.1-typhoon2-8b-instruct
set QWEN_VISION=0

# ทางเลือกเดิม: Qwen3 บน vLLM
# set QWEN_BASE_URL=http://<server-ip>:8000/v1
# set QWEN_MODEL=Qwen/Qwen3-8B

# ถ้าสลับไปรุ่นมองรูปได้ (เช่น Qwen3-VL) เปิด vision เพื่อส่งรูปเข้า LLM ตรงๆ
# set QWEN_VISION=1
```
เสิร์ฟผ่าน vLLM / Ollama / LM Studio ใช้ **OpenAI-compatible API** เหมือนกันหมด → เปลี่ยนแค่ URL + ชื่อ model

## ต่อ faster-whisper (ถอดเสียงจริง)

```bash
pip install faster-whisper
set WHISPER_DEVICE=cuda      # ถ้ามี GPU (ไม่มี = cpu, ช้า)
```

## ไฟล์ในโฟลเดอร์

| ไฟล์ | หน้าที่ |
|------|--------|
| `app.py` | เว็บ FastAPI + รับ input + ต่อ pipeline (เสิร์ฟหน้า Jinja2) |
| `transcribe.py` | เสียง → ข้อความ (faster-whisper / mock) |
| `llm.py` | LLM (Typhoon) ดึง JSON เครื่องจักร + render .md (mock ถ้าต่อไม่ได้) |
| `templates/index.html` | หน้าเว็บ (ฟอร์ม + ผลลัพธ์) |

## input ที่รองรับ
1. **ไฟล์เสียงประชุม** — ถอดเป็น transcript
2. **รูปภาพ + caption ใต้รูป** — เช่น รูปมอเตอร์ + "มอเตอร์เสีย"

ทั้งสองรวมเป็น context เดียวป้อน LLM (Typhoon) → ได้ตารางเครื่องจักร + ไฟล์ `.md`
