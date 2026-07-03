"""
แปลงข้อความคำตอบ -> เสียงพูดไทย (TTS)

2 engine (เลือกด้วย env TTS_ENGINE):
  - "windows" = Microsoft Pattara (OneCore) ผ่าน PowerShell/WinRT — offline 100%, CPU, ไม่ต้องเน็ต
  - "edge"    = edge-tts (th-TH-NiwatNeural) — ออนไลน์ ฟรี เสียง Neural คุณภาพสูงกว่า แต่ต้องต่อเน็ต

graceful degradation (เหมือน transcribe.py/llm.py):
  - engine ที่เลือกล้มเหลว -> คืน None ให้ฝั่งเว็บ fallback เสียงสังเคราะห์ของเบราว์เซอร์ (SpeechSynthesis)
คืนค่าเป็น (bytes, media_type) — windows=audio/wav, edge=audio/mpeg
"""
import os, subprocess, tempfile, uuid
from dotenv import load_dotenv
load_dotenv()

TTS_ENGINE = os.getenv("TTS_ENGINE", "windows").strip().lower()   # "windows" | "edge"

# edge-tts: th-TH-NiwatNeural = ชายไทย (JARVIS) ; th-TH-PremwadeeNeural = หญิงไทย
TTS_VOICE = os.getenv("TTS_VOICE", "th-TH-NiwatNeural")
TTS_RATE  = os.getenv("TTS_RATE", "+0%")
TTS_PITCH = os.getenv("TTS_PITCH", "+0Hz")

# windows: ชื่อเสียง OneCore ("" = เลือกไทยตัวแรก = Microsoft Pattara)
TTS_WIN_VOICE = os.getenv("TTS_WIN_VOICE", "")
_PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_windows.ps1")


async def synthesize(text):
    """แปลงข้อความ -> (audio_bytes, media_type). คืน None ถ้าทำไม่ได้ (ให้ฝั่งเว็บ fallback)"""
    text = (text or "").strip()
    if not text:
        return None
    if TTS_ENGINE == "windows":
        return _synthesize_windows(text)
    return await _synthesize_edge(text)


def _synthesize_windows(text):
    """Windows OneCore (Pattara) ผ่าน PowerShell/WinRT -> (wav bytes, 'audio/wav'). offline"""
    tmp = tempfile.gettempdir()
    tag = uuid.uuid4().hex
    txt_path = os.path.join(tmp, f"tts_{tag}.txt")
    wav_path = os.path.join(tmp, f"tts_{tag}.wav")
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _PS1,
               "-InFile", txt_path, "-OutFile", wav_path]
        if TTS_WIN_VOICE:
            cmd += ["-Voice", TTS_WIN_VOICE]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        with open(wav_path, "rb") as f:
            data = f.read()
        return (data, "audio/wav") if data else None
    except Exception as e:
        err = e.stderr.decode("utf-8", "ignore")[:300] if getattr(e, "stderr", None) else ""
        print(f"[TTS] windows failed ({type(e).__name__}: {e}) {err} -> web fallback (browser voice)")
        return None
    finally:
        for p in (txt_path, wav_path):
            try: os.remove(p)
            except OSError: pass


async def _synthesize_edge(text):
    """edge-tts (Neural, ออนไลน์) -> (mp3 bytes, 'audio/mpeg')"""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
        buf = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return (bytes(buf), "audio/mpeg") if buf else None
    except Exception as e:
        print(f"[TTS] edge ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ฝั่งเว็บจะใช้เสียงเบราว์เซอร์แทน")
        return None
