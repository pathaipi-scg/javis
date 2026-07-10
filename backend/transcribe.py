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

# เลือกเครื่องถอดเสียง: whisper(ค่าเริ่มต้น) | gemini
#   gemini = ส่งเสียงขึ้น Google Gemini ถอด (ไม่กิน GPU เครื่อง แต่ต้องเน็ต+มี GEMINI_API_KEY)
#   ล้มเหลว -> ตกไป remote/local whisper -> mock (graceful degradation เหมือนเดิม)
STT_ENGINE = os.getenv("STT_ENGINE", "whisper").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL", "gemini-2.5-flash")
# prompt สั่งให้ถอดคำต่อคำ ไม่เติมความเห็น/timestamp — คงศัพท์ช่างไทย
_GEMINI_STT_PROMPT = (
    "ถอดเสียงพูดภาษาไทยในไฟล์นี้เป็นข้อความแบบคำต่อคำ (verbatim) "
    "เป็นบทสนทนาประชุมซ่อมบำรุงเครื่องจักร (มอเตอร์ ปั๊ม สายพาน แบริ่ง ไฮดรอลิก วาล์ว เซนเซอร์) "
    "ตอบเฉพาะข้อความที่ถอดได้เท่านั้น ห้ามเติมคำอธิบาย ห้ามใส่ timestamp ห้ามใส่เครื่องหมายคำพูด"
)
# mime ตามนามสกุลไฟล์ (Gemini รองรับ wav/mp3/aac/ogg/flac/aiff; webm ไม่อยู่ในลิสต์ทางการ)
_GEMINI_MIME = {".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/aac",
                ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
                ".aiff": "audio/aiff", ".webm": "audio/webm"}


def _add_cuda_dll_dirs():
    """ทำให้ ctranslate2 หา cuDNN/cuBLAS เจอบน Windows (จาก nvidia-*-cu12 ที่ pip ลง)

    ctranslate2 โหลด cublas64_12.dll / cudnn64_9.dll แบบ lazy ตอน inference
    การแค่ add_dll_directory ไม่พอ — ctranslate2 เรียก LoadLibrary แบบไม่ค้น dir นั้น
    เลยเจอ 'cublas64_12.dll is not found' แล้วตกไป mock
    ทางที่ได้ผลคือ preload DLL เข้า process ด้วย ctypes ก่อน
    พอ ctranslate2 lazy-load ทีหลัง Windows จะคืนตัวที่โหลดไว้แล้วให้ -> เจอ"""
    import glob, site, ctypes
    sp_dirs = list(site.getsitepackages())
    try:
        sp_dirs.append(site.getusersitepackages())
    except Exception:
        pass
    for sp in sp_dirs:
        for bindir in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            if os.path.isdir(bindir):
                try:
                    os.add_dll_directory(bindir)
                except Exception:
                    pass
                os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
    # preload DLL หลัก (dependency ในโฟลเดอร์เดียวกันจะตามมาเอง)
    for dll in ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.CDLL(dll)
        except Exception:
            pass


_add_cuda_dll_dirs()


def transcribe_audio(path):
    """ถอดเสียง -> ข้อความ. gemini(ถ้าเลือก) -> server(ถ้าตั้ง) -> local whisper -> mock"""
    if STT_ENGINE == "gemini":
        try:
            return _transcribe_gemini(path)
        except Exception as e:
            print(f"[STT] gemini ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ตกไป whisper")
    if STT_BASE_URL:
        try:
            return _transcribe_remote(STT_BASE_URL, path)
        except Exception as e:
            print(f"[STT] remote ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ถอดในเครื่องแทน")
    return _transcribe_local(path)


def _transcribe_gemini(path):
    """ส่งเสียงขึ้น Gemini (generateContent + inline audio) -> transcript คำต่อคำ"""
    import base64, requests
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ยังไม่ได้ตั้งใน .env")
    ext = os.path.splitext(path)[1].lower()
    mime = _GEMINI_MIME.get(ext, "audio/wav")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    url = f"{GEMINI_BASE_URL}/models/{GEMINI_STT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"parts": [
            {"text": _GEMINI_STT_PROMPT},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    resp = requests.post(url, json=body, timeout=STT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    cands = data.get("candidates", [])
    if not cands:
        raise RuntimeError(f"Gemini คืนว่าง (อาจโดน safety block): {str(data)[:200]}")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini ไม่คืนข้อความถอดเสียง")
    return text


def _transcribe_remote(base_url, path):
    """ส่งไฟล์เสียงไปถอดที่ STT service บน server -> คืน transcript"""
    import requests
    url = base_url.rstrip("/") + "/transcribe"
    with open(path, "rb") as f:
        resp = requests.post(url, files={"file": (os.path.basename(path), f)}, timeout=STT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["transcript"]


import threading

_model = None            # cache โมเดลไว้ในหน่วยความจำ — โหลด large-v3 เข้า GPU ครั้งเดียว ใช้ซ้ำ
_model_lock = threading.Lock()   # กัน warm-up (thread เบื้องหลัง) ชนกับ request แรก -> โหลดซ้อน


def _get_model():
    """คืน WhisperModel ตัวเดียวใช้ซ้ำ (สร้างใหม่ทุก request = โหลดโมเดลซ้ำ ~3s เสียเปล่า)"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:   # เช็คซ้ำในล็อก — thread อื่นอาจโหลดเสร็จระหว่างรอ
                from faster_whisper import WhisperModel
                compute = "float16" if WHISPER_DEVICE == "cuda" else "int8"
                _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=compute)
    return _model


def _transcribe_local(path):
    """ถอดในเครื่องด้วย faster-whisper; ถ้าไม่มี -> mock"""
    try:
        model = _get_model()
        lang = None if WHISPER_LANG.lower() == "auto" else WHISPER_LANG
        segments, _ = model.transcribe(
            path, language=lang, vad_filter=True,
            initial_prompt="ประชุมซ่อมบำรุงเครื่องจักร มอเตอร์ ปั๊มน้ำ สายพานลำเลียง "
                           "แบริ่ง ลูกปืน ไฮดรอลิก วาล์ว เซนเซอร์ ลัดวงจร เขม่า "
                           "แรงดันตก ความร้อน สั่น รั่วซึม forming press "
                           "อาการ สาเหตุ วิธีแก้ เปลี่ยนอะไหล่",
            condition_on_previous_text=False,   # กันวนซ้ำ (hallucination loop)
            compression_ratio_threshold=2.4,    # ตัด segment ที่ดูเป็นขยะ
            no_speech_threshold=0.6,             # ข้ามช่วงไม่มีคนพูด
        )
        out = []
        for s in segments:
            out.append(f"[{s.start:05.1f}s] {s.text.strip()}")
        return "\n".join(out) if out else "(ไม่พบเสียงพูด)"

    except ModuleNotFoundError as e:
        reason = f"ยังไม่ได้ลง faster-whisper: {e.name}"
        return _mock_transcript(reason)
    except Exception as e:
        # ลงแล้วแต่ถอดไม่สำเร็จ (ไฟล์เสีย / CUDA หาย / โมเดลโหลดไม่ได้ ฯลฯ)
        reason = f"ถอดเสียงล้มเหลว: {type(e).__name__}: {e}"
        return _mock_transcript(reason)


def _mock_transcript(reason):
    return (
        f"[MOCK — {reason}]\n"
        "[00:31s] เครื่อง A มอเตอร์ปั๊มน้ำไหม้เมื่อเช้า\n"
        "[00:38s] ซ่อมล่าสุดไป 20 มิถุนา เปลี่ยนมอเตอร์ใหม่"
    )
