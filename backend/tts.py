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

TTS_ENGINE = os.getenv("TTS_ENGINE", "openai").strip().lower()   # "openai" | "gemini" | "windows"

# ---- Gemini TTS (ผ่าน endpoint บริษัท เท่านั้น) ----
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL  = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "").strip() or "Charon"   # ว่าง/ไม่ตั้ง -> Charon (ชายทุ้ม); กัน Gemini เลือกเสียงหญิงเอง
GEMINI_TTS_TIMEOUT = int(os.getenv("GEMINI_TTS_TIMEOUT", "60"))

# JARVIS DSP (numpy ผ่าน PyAV): band-limit + presence + echo ห้องแคบ + normalize
#   ให้เสียง comms/AI: ตัดเบส-ตัดไฮ + ดันย่านกลางให้คม + echo สั้น = ห้องแคบ
#   TTS_FX=1 เปิด ; PyAV ใช้ไม่ได้ -> ข้าม คืนเสียงดิบ (graceful)
TTS_FX = os.getenv("TTS_FX", "1").strip() not in ("0", "", "false", "no")   # default เปิด (comms/JARVIS band-limit ใกล้คลิปต้นฉบับ); TTS_FX=0 = เสียงดิบ
TTS_PITCH = float(os.getenv("TTS_PITCH", "0"))               # ปรับ pitch เป็น semitone (ลบ=ทุ้มลง); 0=ปิด
TTS_FX_HP        = float(os.getenv("TTS_FX_HP", "120"))        # highpass Hz (ตัดเบสบาง)
TTS_FX_LP        = float(os.getenv("TTS_FX_LP", "5000"))       # lowpass Hz (ตัดไฮ)
TTS_FX_PRESENCE   = float(os.getenv("TTS_FX_PRESENCE", "1.0")) # gain ย่านสูง (1.0=ปิด; สูงไป=เสียงหวีด)
TTS_FX_PRESENCE_F = float(os.getenv("TTS_FX_PRESENCE_F", "1800"))  # ความถี่เริ่มบูสต์
TTS_FX_ECHO_MS   = float(os.getenv("TTS_FX_ECHO_MS", "22"))    # echo delay ms (ห้องแคบ)
TTS_FX_ECHO_GAIN = float(os.getenv("TTS_FX_ECHO_GAIN", "0.0")) # echo ความดัง 0-1 (0=ปิด กัน comb ring)

# windows: ชื่อเสียง OneCore ("" = เลือกไทยตัวแรก = Microsoft Pattara)
TTS_WIN_VOICE = os.getenv("TTS_WIN_VOICE", "")
_PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_windows.ps1")


def _speed_for(text):
    """เลือกจังหวะพูดตามภาษา: อังกฤษล้วน (ไม่มีอักษรไทย) -> ช้ากว่า (TTS_SPEED_EN)
    ไทย/ปนไทย -> TTS_SPEED เดิม. อังกฤษที่ speed 1.3 ฟังเร็วเกิน จึงแยก"""
    import re, openai_audio as oa
    is_en = (not re.search("[฀-๿]", text or "")) and bool(re.search(r"[A-Za-z]", text or ""))
    return oa.TTS_SPEED_EN if is_en else oa.TTS_SPEED


async def synthesize(text):
    """แปลงข้อความ -> (audio_bytes, media_type). คืน None ถ้าทำไม่ได้ (ให้ฝั่งเว็บ fallback)"""
    text = (text or "").strip()
    if not text:
        return None
    if TTS_ENGINE == "windows":
        return _synthesize_windows(text)
    if TTS_ENGINE == "openai":
        return _synthesize_openai(text)
    return _synthesize_gemini(text)


def stream_openai(text):
    """generator: yield mp3 chunks จาก gpt-4o-mini-tts แบบ streaming -> เสียงแรก ~0.8s
    ใช้กับ /api/tts-stream (เล่นทันทีที่ byte แรกมา). ไม่ผ่าน FX/pitch (stream ต้องทยอยส่ง)"""
    import openai_audio as oa
    client = oa.get_client()
    kw = dict(model=oa.TTS_MODEL, voice=oa.TTS_VOICE, input=text,
              response_format="mp3", speed=_speed_for(text))
    def _open():
        try:
            return client.audio.speech.with_streaming_response.create(instructions=oa.TTS_INSTRUCTIONS, **kw) \
                if oa.TTS_INSTRUCTIONS else client.audio.speech.with_streaming_response.create(**kw)
        except TypeError:
            return client.audio.speech.with_streaming_response.create(**kw)   # lib เก่าไม่รับ instructions
    with _open() as r:
        for chunk in r.iter_bytes(4096):
            if chunk:
                yield chunk


def _synthesize_openai(text):
    """gpt-4o-mini-tts (เร็ว+steerable) -> (bytes, media_type). ล้มเหลว -> None (fallback เบราว์เซอร์)
    wav -> ผ่าน JARVIS FX ได้ ; instructions สั่งโทน JARVIS (ตั้งใน .env)"""
    try:
        import openai_audio as oa
        client = oa.get_client()
        kw = dict(model=oa.TTS_MODEL, voice=oa.TTS_VOICE, input=text,
                  response_format=oa.TTS_FORMAT, speed=_speed_for(text))
        try:
            r = client.audio.speech.create(instructions=oa.TTS_INSTRUCTIONS, **kw) if oa.TTS_INSTRUCTIONS \
                else client.audio.speech.create(**kw)
        except TypeError:
            r = client.audio.speech.create(**kw)     # lib เก่าไม่รับ instructions
        data = r.read() if hasattr(r, "read") else r.content
        if not data:
            return None
        if oa.TTS_FORMAT == "wav":
            return _jarvis_fx(data)                  # FX ในเครื่อง (ปิดด้วย TTS_FX=0 ถ้า instructions พอ)
        mt = {"mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac", "flac": "audio/flac"}
        return (data, mt.get(oa.TTS_FORMAT, "audio/mpeg"))
    except Exception as e:
        print(f"[TTS] openai ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ฝั่งเว็บจะใช้เสียงเบราว์เซอร์แทน")
        return None


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
    if not TTS_FX and not TTS_PITCH:
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

        # --- pitch shift (semitone) ทำเสียงทุ้ม/สูง — resample แบบ tape (ทุ้มลง=ยาวขึ้นเล็กน้อย) ---
        if TTS_PITCH:
            pf = 2.0 ** (TTS_PITCH / 12.0)          # <1 = ทุ้มลง
            n2 = max(1, int(round(len(x) / pf)))
            x = np.interp(np.linspace(0, len(x) - 1, n2), np.arange(len(x)), x)

        if not TTS_FX:
            y = x
        else:
            # --- band-limit + presence (zero-phase FFT) ---
            # pad เป็น power-of-2 -> FFT เร็ว (ไม่ pad = ความยาวมั่ว/prime ทำ FFT ช้าเป็นวินาที)
            n = len(x)
            nfft = 1 << int(np.ceil(np.log2(max(n, 2))))
            X = np.fft.rfft(x, nfft)
            f = np.fft.rfftfreq(nfft, 1.0 / sr)
            X[f < TTS_FX_HP] = 0.0
            X[f > TTS_FX_LP] = 0.0
            if TTS_FX_PRESENCE != 1.0:
                X[f > TTS_FX_PRESENCE_F] *= TTS_FX_PRESENCE
            y = np.fft.irfft(X, nfft)[:n]

        # --- echo สั้น = ห้องแคบ (เฉพาะตอนเปิด FX) ---
        d = int(TTS_FX_ECHO_MS * 0.001 * sr)
        if TTS_FX and d > 0 and TTS_FX_ECHO_GAIN > 0:
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
