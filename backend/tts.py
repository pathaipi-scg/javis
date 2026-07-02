"""
แปลงข้อความคำตอบ -> เสียงพูดไทย (TTS) ด้วย edge-tts (ออนไลน์ ฟรี ไม่ต้อง API key)

เสียง "JARVIS" = เสียงผู้ชายไทย th-TH-NiwatNeural (ปรับ pitch ให้ทุ้มเป็น AI ได้ทาง .env)
graceful degradation (เหมือน transcribe.py/llm.py):
  - ถ้า edge-tts ไม่ได้ลง หรือเน็ตต่อ Microsoft ไม่ติด -> คืน None
    ฝั่งเว็บจะ fallback ไปใช้เสียงสังเคราะห์ของเบราว์เซอร์แทน (คุณภาพต่ำกว่า แต่ไม่ล่ม)
"""
import os
from dotenv import load_dotenv
load_dotenv()

# th-TH-NiwatNeural = ชายไทย (JARVIS) ; th-TH-PremwadeeNeural = หญิงไทย
TTS_VOICE = os.getenv("TTS_VOICE", "th-TH-NiwatNeural")
TTS_RATE  = os.getenv("TTS_RATE", "+0%")     # ความเร็วพูด เช่น "-5%" ช้าลง, "+10%" เร็วขึ้น
TTS_PITCH = os.getenv("TTS_PITCH", "+0Hz")   # โทนเสียง เช่น "-8Hz" ทุ้มลงให้ดูเป็น AI ผู้ชาย


async def synthesize(text):
    """แปลงข้อความ -> mp3 bytes. คืน None ถ้าทำไม่ได้ (ให้ฝั่งเว็บ fallback)"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
        buf = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf) or None
    except Exception as e:
        print(f"[TTS] ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ฝั่งเว็บจะใช้เสียงเบราว์เซอร์แทน")
        return None
