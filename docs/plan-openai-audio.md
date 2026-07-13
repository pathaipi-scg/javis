# แผน: ย้าย STT/TTS ไป gpt-4o audio (Azure OpenAI)

> สถานะ: **แผน** ยังไม่แก้โค้ดจริง — เทส creds ผ่านแล้ว (ดูหัวข้อ "ผลทดสอบ")

## เป้าหมาย
เปลี่ยน TTS/STT จาก Gemini → **gpt-4o-mini-tts** + **gpt-4o-transcribe** เพื่อ **latency ต่ำลง ~2x**
โดยยังใช้บัญชี Azure ของบริษัท (compliant) และ **คง Gemini/whisper/windows ไว้สลับได้**

## ทำไม (Gemini ช้า)
- `gemini-2.5-flash-preview-tts` = preview, ไม่ optimize latency + **ไม่ stream** (ปั้นทั้งก้อนก่อนส่ง) + floor ~4s
- gpt-4o-mini-tts = production, **stream ได้** (เสียงแรก <1s), engine เสียงเฉพาะทาง

## ผลทดสอบ (เทสด้วย creds Azure จริงแล้ว — ผ่าน)
| | Gemini | gpt-4o audio |
|---|---|---|
| TTS | 8s | 3.9s (เต็มก้อน) / <1s (stream) |
| STT | 3-4s | 1.8s + ถอดไทยเป๊ะ |

เสียงตัวอย่าง: `Downloads/jarvis_openai_tts.wav` (voice onyx)

## ขอบเขตงาน (โค้ด)
1. **`backend/tts.py`** — เพิ่ม engine `openai`
   - `_synthesize_openai(text)`: client (AzureOpenAI/OpenAI) → `audio.speech.create(model=deployment, voice, input, instructions, response_format=wav)`
   - **streaming + หั่นประโยค** (reuse แนวคิด chunk ที่ทำใน frontend) ให้เสียงแรกมาไว
   - รองรับ `instructions` (steer โทน JARVIS) + `voice`
   - fallback: ล้ม → None (เบราว์เซอร์อ่าน) เหมือนเดิม
2. **`backend/transcribe.py`** — เพิ่ม engine `openai`
   - `_transcribe_openai(path)`: `audio.transcriptions.create(model=deployment, file, language=th)`
   - ต่อ chain: openai → (remote) → whisper local → mock
3. **client helper** — AzureOpenAI (provider=azure) หรือ OpenAI (provider=openai) ตาม env
4. **`app.py`** — `/api/stt-config` / model badge เผย engine ที่ใช้ (option)

## env ที่ใช้ (ร่างใน `.env.example` แล้ว)
- provider: `OPENAI_AUDIO_PROVIDER` (azure|openai)
- azure: `OPENAI_AUDIO_ENDPOINT` + `OPENAI_AUDIO_API_KEY` + `OPENAI_AUDIO_API_VERSION`(default ได้) + `OPENAI_TTS_DEPLOYMENT` + `OPENAI_STT_DEPLOYMENT`
- openai ตรง: `OPENAI_AUDIO_BASE_URL` + key + `OPENAI_TTS_MODEL`/`OPENAI_STT_MODEL`
- จูนเสียง: `OPENAI_TTS_VOICE`(onyx/ash) + `OPENAI_TTS_INSTRUCTIONS`(โทน JARVIS) + `OPENAI_TTS_FORMAT`(wav) + `OPENAI_STT_LANG`(th)
- เปิดใช้: `TTS_ENGINE=openai` / `STT_ENGINE=openai`

## จูนเสียง JARVIS (ไม่ต้องแก้โค้ด)
- `voice=onyx` (ทุ้ม) + `instructions=พูดทุ้มต่ำ นิ่ง สุขุม มั่นใจ สุภาพ แบบผู้ช่วย AI จังหวะช้าเล็กน้อย`
- JARVIS FX (band-limit/echo ในเครื่อง) ทับได้ถ้าอยาก comms มากขึ้น — แต่ instructions อาจพอ

## ขั้นตอน
1. wire `_synthesize_openai` + client helper ใน tts.py (ยัง default gemini)
2. wire `_transcribe_openai` ใน transcribe.py
3. เทสในเครื่อง: `TTS_ENGINE=openai` / `STT_ENGINE=openai`
4. เทียบเสียง onyx/ash/echo/sage + จูน instructions
5. ถ้าโอเค → ตั้ง default เป็น openai; ไม่โอเค → สลับกลับ gemini ทันที (env)

## rollback
env เดียว: `TTS_ENGINE=gemini` / `STT_ENGINE=gemini` (หรือ whisper) → กลับพฤติกรรมเดิม 100%

## คำถามเปิด
1. streaming ฝั่ง frontend — เล่น audio stream (MediaSource) หรือรับเป็นไฟล์เดียวไปก่อน (ง่ายกว่า, ยัง 3.9s)?
2. ตั้ง openai เป็น default เลย หรือให้เลือกใน UI (เหมือน dropdown โมเดล LLM)?
3. ใช้ instructions อย่างเดียว หรือคง JARVIS FX ทับ?
4. resource Azure ตัวเดียวกับ GPT-5.4 หรือแยก (กระทบ key/endpoint ใน env)
