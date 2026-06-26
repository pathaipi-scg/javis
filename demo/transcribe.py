"""
ถอดเสียงประชุม -> ข้อความ

มี 3 ชั้น (graceful degradation):
  1. ถ้าตั้ง STT_BASE_URL -> ส่งไฟล์ไปถอดที่ STT service บน server (แนะนำ, ใช้ GPU server ได้)
  2. ไม่งั้น -> ถอดในเครื่องด้วย faster-whisper
  3. ทั้งคู่ใช้ไม่ได้ -> คืน mock transcript เพื่อให้ demo เดินต่อได้
"""
import os
from dotenv import load_dotenv
load_dotenv()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # "cuda" ถ้ามี GPU
WHISPER_LANG = os.getenv("WHISPER_LANG", "th")       # "auto" = ตรวจภาษาเอง, "en" = อังกฤษ
STT_BASE_URL = os.getenv("STT_BASE_URL", "").strip() # เช่น http://10.28.254.4:8900 ; ว่าง = ถอดในเครื่อง
STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", "1800"))  # วินาที (คลิปยาวใช้เวลานาน)


def transcribe_audio(path):
    """ถอดเสียง -> ข้อความ. ลอง server ก่อน (ถ้าตั้ง), ตกไป local, สุดท้าย mock"""
    if STT_BASE_URL:
        try:
            return _transcribe_remote(STT_BASE_URL, path)
        except Exception as e:
            print(f"[STT] remote ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ถอดในเครื่องแทน")
    return _transcribe_local(path)


def _transcribe_remote(base_url, path):
    """ส่งไฟล์เสียงไปถอดที่ STT service บน server -> คืน transcript"""
    import requests
    url = base_url.rstrip("/") + "/transcribe"
    with open(path, "rb") as f:
        resp = requests.post(url, files={"file": (os.path.basename(path), f)}, timeout=STT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["transcript"]


def _transcribe_local(path):
    """ถอดในเครื่องด้วย faster-whisper; ถ้าไม่มี -> mock"""
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
