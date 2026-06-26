"""
STT service สำหรับรันบน server (แปลงเสียง -> ข้อความ ด้วย faster-whisper)
เครื่อง local ส่งไฟล์เสียงมาที่ POST /transcribe -> คืน transcript กลับไป

โหลดโมเดลครั้งเดียวตอน startup (ไม่โหลดซ้ำทุก request)
ตั้งค่าผ่าน env (ดู .env.example) — พอมี GPU ค่อยเปลี่ยน WHISPER_DEVICE=cuda + WHISPER_MODEL=large-v3
"""
import os, tempfile
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException

load_dotenv()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")   # "cuda" ถ้ามี GPU
WHISPER_LANG = os.getenv("WHISPER_LANG", "th")        # "auto" = ตรวจภาษาเอง

# พารามิเตอร์ถอดเสียง — ตรงกับ demo/transcribe.py เพื่อให้ผลถอดเหมือนกัน
INITIAL_PROMPT = "ประชุมซ่อมบำรุงเครื่องจักร มอเตอร์ ปั๊ม สายพาน แบริ่ง"

# โหลดโมเดลครั้งเดียว เก็บไว้ใน state
_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from faster_whisper import WhisperModel
    compute = "float16" if WHISPER_DEVICE == "cuda" else "int8"
    print(f"[STT] loading model={WHISPER_MODEL} device={WHISPER_DEVICE} compute={compute} ...")
    _state["model"] = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=compute)
    print("[STT] model ready")
    yield
    _state.clear()


app = FastAPI(title="STT service", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok" if _state.get("model") else "loading",
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "lang": WHISPER_LANG,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    model = _state.get("model")
    if model is None:
        raise HTTPException(503, "model ยังโหลดไม่เสร็จ")

    # เซฟไฟล์ที่อัปโหลดลง temp (faster-whisper อ่านจาก path)
    suffix = os.path.splitext(file.filename or "")[1] or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
        tmp.close()

        lang = None if WHISPER_LANG.lower() == "auto" else WHISPER_LANG
        segments, info = model.transcribe(
            tmp.name, language=lang, vad_filter=True,
            initial_prompt=INITIAL_PROMPT,
            condition_on_previous_text=False,   # กันวนซ้ำ (hallucination loop)
            compression_ratio_threshold=2.4,    # ตัด segment ที่ดูเป็นขยะ
            no_speech_threshold=0.6,             # ข้ามช่วงไม่มีคนพูด
        )
        out = [f"[{s.start:05.1f}s] {s.text.strip()}" for s in segments]
        transcript = "\n".join(out) if out else "(ไม่พบเสียงพูด)"
        return {
            "transcript": transcript,
            "model": WHISPER_MODEL,
            "device": WHISPER_DEVICE,
            "language": getattr(info, "language", lang),
        }
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("STT_PORT", "8900"))
    uvicorn.run(app, host="0.0.0.0", port=port)
