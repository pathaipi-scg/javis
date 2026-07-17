"""
client + config สำหรับ OpenAI audio (gpt-4o-mini-tts / gpt-4o-transcribe)
ใช้ร่วมกันโดย tts.py (_synthesize_openai) และ transcribe.py (_transcribe_openai)

provider = azure (แนะนำ, บัญชีบริษัท) | openai (ตรง)
  azure : OPENAI_AUDIO_ENDPOINT + OPENAI_AUDIO_API_KEY + OPENAI_AUDIO_API_VERSION
          + OPENAI_TTS_DEPLOYMENT / OPENAI_STT_DEPLOYMENT   (ชื่อ deployment ใน Azure)
  openai: OPENAI_AUDIO_API_KEY + OPENAI_AUDIO_BASE_URL + OPENAI_TTS_MODEL / OPENAI_STT_MODEL
ถ้าไม่ตั้งค่า audio แยก -> fallback ใช้ค่า Azure ของ LLM (AZURE_OPENAI_*) resource เดียวกันได้
"""
import os
from dotenv import load_dotenv
load_dotenv()

PROVIDER = os.getenv("OPENAI_AUDIO_PROVIDER", "azure").strip().lower()

# endpoint/key/version — ไม่ตั้งแยก -> ใช้ของ LLM (resource เดียวกับ GPT-5.4)
_ENDPOINT = os.getenv("OPENAI_AUDIO_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", "")).strip()
_KEY      = os.getenv("OPENAI_AUDIO_API_KEY", os.getenv("AZURE_OPENAI_API_KEY", "")).strip()
_VER      = os.getenv("OPENAI_AUDIO_API_VERSION", os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")).strip()
_BASE     = os.getenv("OPENAI_AUDIO_BASE_URL", "https://api.openai.com/v1").strip()

# ชื่อโมเดล/deployment (deployment สำหรับ azure, model id สำหรับ openai ตรง)
TTS_MODEL = os.getenv("OPENAI_TTS_DEPLOYMENT", os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")).strip()
STT_MODEL = os.getenv("OPENAI_STT_DEPLOYMENT", os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe")).strip()

# จูนเสียง
TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "").strip() or "verse"         # default verse; onyx/ash/echo ทุ้มกว่า
TTS_SPEED = float(os.getenv("OPENAI_TTS_SPEED", "1.3"))                  # จังหวะพูด 0.25-4.0 (>1 = เร็วขึ้น)
TTS_SPEED_EN = float(os.getenv("OPENAI_TTS_SPEED_EN", "1.0"))            # คำตอบอังกฤษพูดช้ากว่า (1.3 เร็วไปสำหรับอังกฤษ)
# instruction เน้นความชัด+กระชับ (เลี่ยงคำที่ทำให้พูดช้า เช่น "นิ่ง/สุขุม/มั่นใจ")
TTS_INSTRUCTIONS = os.getenv("OPENAI_TTS_INSTRUCTIONS",
                             "ออกเสียงชัดถ้อยชัดคำ กระชับ ฉับไว").strip()
TTS_FORMAT = os.getenv("OPENAI_TTS_FORMAT", "wav").strip().lower()       # wav เข้ากับ JARVIS FX ได้เลย
STT_LANG   = os.getenv("OPENAI_STT_LANG", "th").strip()   # "th" | "en" | "auto"(ตรวจภาษาเอง ไทย/อังกฤษ)
# prompt anchor — bias ถอดเป็นไทย (กันหลอนลาวตอนเสียงไม่ชัด) + คงศัพท์เทคนิคอังกฤษไว้ตามเดิม
STT_PROMPT = os.getenv("OPENAI_STT_PROMPT",
    "บทสนทนาซ่อมบำรุงเครื่องจักรภาษาไทย อาการ สาเหตุ วิธีแก้ ปั๊มน้ำ สายพาน แรงดันตก สั่น รั่วซึม. "
    "คงคำศัพท์เทคนิคภาษาอังกฤษไว้ตามเดิม ไม่ต้องทับศัพท์เป็นไทย เช่น "
    "forming press, pressure drop, motor, bearing, vibration, hydraulic, valve, sensor, conveyor, overheat").strip()
# prompt กลาง ไม่ล็อกภาษา — ใช้ตอน STT_LANG=auto ให้ถอดตามภาษาที่พูดจริง (ไทยหรืออังกฤษ)
STT_PROMPT_AUTO = os.getenv("OPENAI_STT_PROMPT_AUTO",
    "Machine maintenance meeting, Thai or English. Transcribe verbatim in the language actually spoken. "
    "Keep technical terms: motor, pump, bearing, hydraulic, valve, sensor, conveyor, forming press, overheat.").strip()

_client = None


def get_client():
    """สร้าง client ครั้งเดียวใช้ซ้ำ (AzureOpenAI หรือ OpenAI ตาม provider)"""
    global _client
    if _client is None:
        if not _KEY:
            raise RuntimeError("OPENAI_AUDIO_API_KEY (หรือ AZURE_OPENAI_API_KEY) ยังไม่ได้ตั้งใน .env")
        if PROVIDER == "azure":
            from openai import AzureOpenAI
            _client = AzureOpenAI(azure_endpoint=_ENDPOINT, api_key=_KEY, api_version=_VER)
        else:
            from openai import OpenAI
            _client = OpenAI(api_key=_KEY, base_url=_BASE)
    return _client
