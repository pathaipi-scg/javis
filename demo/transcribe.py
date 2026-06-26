"""
ถอดเสียงประชุม -> ข้อความ ด้วย faster-whisper
ถ้ายังไม่ลง faster-whisper -> คืน mock transcript เพื่อให้ demo เดินต่อได้
"""
import os
from dotenv import load_dotenv
load_dotenv()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # "cuda" ถ้ามี GPU
WHISPER_LANG = os.getenv("WHISPER_LANG", "th")       # "auto" = ตรวจภาษาเอง, "en" = อังกฤษ


def transcribe_audio(path):
    try:
        from faster_whisper import WhisperModel
        compute = "float16" if WHISPER_DEVICE == "cuda" else "int8"
        model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=compute)
        lang = None if WHISPER_LANG.lower() == "auto" else WHISPER_LANG
        segments, _ = model.transcribe(
            path, language=lang, vad_filter=True,
            initial_prompt="ประชุมซ่อมบำรุงเครื่องจักร มอเตอร์ ปั๊ม สายพาน แบริ่ง",
            condition_on_previous_text=False,   # กันวนซ้ำ (hallucination loop)
            compression_ratio_threshold=2.4,    # ตัด segment ที่ดูเป็นขยะ
            no_speech_threshold=0.6,             # ข้ามช่วงไม่มีคนพูด
        )
        out = []
        for s in segments:
            out.append(f"[{s.start:05.1f}s] {s.text.strip()}")
        return "\n".join(out) if out else "(ไม่พบเสียงพูด)"

    except Exception as e:
        return (
            f"[MOCK — ยังไม่ได้ลง faster-whisper: {type(e).__name__}]\n"
            "[00:31s] เครื่อง A มอเตอร์ปั๊มน้ำไหม้เมื่อเช้า\n"
            "[00:38s] ซ่อมล่าสุดไป 20 มิถุนา เปลี่ยนมอเตอร์ใหม่"
        )
