"""
แปลงข้อความคำตอบ -> เสียงพูดไทย (TTS)

2 engine (เลือกด้วย env TTS_ENGINE):
  - "gemini"  = Gemini TTS — ใช้ key/บัญชี Gemini ของบริษัท (GEMINI_API_KEY) ยิงผ่าน GEMINI_BASE_URL
  - "windows" = Microsoft Pattara (OneCore) ผ่าน PowerShell/WinRT — offline 100%, ไม่ออกเน็ตเลย

graceful degradation (เหมือน transcribe.py/llm.py):
  - engine ที่เลือกล้มเหลว -> คืน None ให้ฝั่งเว็บ fallback เสียงสังเคราะห์ของเบราว์เซอร์ (SpeechSynthesis, ในเครื่อง)
คืนค่าเป็น (bytes, media_type) — windows=audio/wav ; gemini=audio/wav (ผ่าน JARVIS FX)

JARVIS FX (_jarvis_fx): DSP ในเครื่อง (numpy/PyAV, ไม่ออกเน็ต) — band-limit + presence + echo ห้องแคบ + normalize
  ปรับผ่าน env TTS_FX_* ; ปิดด้วย TTS_FX=0
"""
import base64, io, os, subprocess, tempfile, uuid, wave
from dotenv import load_dotenv
load_dotenv()

TTS_ENGINE = os.getenv("TTS_ENGINE", "gemini").strip().lower()   # "gemini" | "windows"

# ---- Gemini TTS (ผ่าน endpoint บริษัท เท่านั้น) ----
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL  = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Charon")   # เสียงชายทุ้ม; เทียบ Charon/Fenrir/Orus
GEMINI_TTS_TIMEOUT = int(os.getenv("GEMINI_TTS_TIMEOUT", "60"))

# JARVIS DSP (numpy ผ่าน PyAV): band-limit + presence + echo ห้องแคบ + normalize
#   ให้เสียง comms/AI: ตัดเบส-ตัดไฮ + ดันย่านกลางให้คม + echo สั้น = ห้องแคบ
#   TTS_FX=1 เปิด ; PyAV ใช้ไม่ได้ -> ข้าม คืนเสียงดิบ (graceful)
TTS_FX = os.getenv("TTS_FX", "1").strip() not in ("0", "", "false", "no")
TTS_FX_HP        = float(os.getenv("TTS_FX_HP", "120"))        # highpass Hz (ตัดเบสบาง)
TTS_FX_LP        = float(os.getenv("TTS_FX_LP", "5000"))       # lowpass Hz (ตัดไฮ)
TTS_FX_PRESENCE   = float(os.getenv("TTS_FX_PRESENCE", "4.0")) # gain ย่านสูง (คม/สว่าง)
TTS_FX_PRESENCE_F = float(os.getenv("TTS_FX_PRESENCE_F", "1200"))  # ความถี่เริ่มบูสต์
TTS_FX_ECHO_MS   = float(os.getenv("TTS_FX_ECHO_MS", "22"))    # echo delay ms (ห้องแคบ)
TTS_FX_ECHO_GAIN = float(os.getenv("TTS_FX_ECHO_GAIN", "0.16"))# echo ความดัง 0-1

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
    return _synthesize_gemini(text)


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


def _synthesize_gemini(text):
    """Gemini TTS (key/บัญชีบริษัท) -> PCM -> ห่อ WAV -> JARVIS FX -> (wav bytes, media_type).
    ล้มเหลว -> None (fallback เสียงเบราว์เซอร์)"""
    try:
        import requests
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY ยังไม่ได้ตั้งใน .env")
        url = f"{GEMINI_BASE_URL}/models/{GEMINI_TTS_MODEL}:generateContent?key={GEMINI_API_KEY}"
        body = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE}}},
            },
        }
        resp = requests.post(url, json=body, timeout=GEMINI_TTS_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        cands = data.get("candidates", [])
        if not cands:
            raise RuntimeError(f"Gemini คืนว่าง (อาจโดน safety block): {str(data)[:200]}")
        parts = cands[0].get("content", {}).get("parts", [])
        b64 = next((p["inlineData"]["data"] for p in parts if p.get("inlineData")), None)
        if not b64:
            raise RuntimeError("Gemini ไม่คืน audio (inlineData)")
        pcm = base64.b64decode(b64)
        # Gemini TTS คืน PCM ดิบ 24kHz mono 16-bit -> ห่อ WAV
        wbuf = io.BytesIO()
        with wave.open(wbuf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        return _jarvis_fx(wbuf.getvalue())     # -> (bytes, media_type) ; FX ในเครื่อง ไม่ออกเน็ต
    except Exception as e:
        print(f"[TTS] gemini ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ฝั่งเว็บจะใช้เสียงเบราว์เซอร์แทน")
        return None


def _jarvis_fx(audio_bytes):
    """JARVIS DSP: audio(wav/mp3) -> EQ curve + echo + normalize -> (wav bytes, 'audio/wav').
    ใช้ PyAV decode + numpy DSP ในเครื่อง (ไม่ออกเน็ต). FX ปิด/ล้มเหลว -> คืน (input, 'audio/wav')"""
    if not TTS_FX:
        return (audio_bytes, "audio/wav")
    try:
        import av, numpy as np
        # --- decode (in-memory) -> mono float @ sr ---
        cont = av.open(io.BytesIO(audio_bytes))
        sr = cont.streams.audio[0].rate
        rs = av.AudioResampler(format="flt", layout="mono", rate=sr)
        parts = []
        for fr in cont.decode(audio=0):
            for r in rs.resample(fr):
                parts.append(r.to_ndarray().reshape(-1))
        if not parts:
            return (audio_bytes, "audio/wav")
        x = np.concatenate(parts).astype(np.float64)

        # --- band-limit + presence (zero-phase FFT) ---
        n = len(x)
        X = np.fft.rfft(x)
        f = np.fft.rfftfreq(n, 1.0 / sr)
        X[f < TTS_FX_HP] = 0.0
        X[f > TTS_FX_LP] = 0.0
        X[f > TTS_FX_PRESENCE_F] *= TTS_FX_PRESENCE
        y = np.fft.irfft(X, n)

        # --- echo สั้น = ห้องแคบ ---
        d = int(TTS_FX_ECHO_MS * 0.001 * sr)
        if d > 0 and TTS_FX_ECHO_GAIN > 0:
            e = np.zeros_like(y)
            e[d:] = y[:-d] * TTS_FX_ECHO_GAIN
            y = y + e

        # --- normalize peak ~0.95 ---
        peak = float(np.max(np.abs(y))) or 1.0
        y = np.clip(y / peak * 0.95, -1.0, 1.0)
        pcm = (y * 32767).astype("<i2")

        wbuf = io.BytesIO()
        with wave.open(wbuf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
        return (wbuf.getvalue(), "audio/wav")
    except Exception as e:
        print(f"[TTS] JARVIS FX error ({type(e).__name__}: {e}) -> เสียงดิบ")
        return (audio_bytes, "audio/wav")
