# แผน: เปลี่ยน STT + TTS ไปใช้ Gemini (Google AI Studio, key AIza…)

## Context (ทำไม)
- **STT ปัจจุบัน = faster-whisper (large-v3) บน GPU** — กิน VRAM แย่งกับ Typhoon+bge+reranker
  ย้ายไป Gemini (คลาวด์) = คืน GPU, ไม่ต้องโหลด Whisper
- **TTS ปัจจุบัน = Windows Pattara / edge-tts** — เสียงไม่ดีพอ อยากลอง Gemini TTS
- **LLM ตอบคำถาม = คงเดิม** (Typhoon local / Azure GPT) — ไม่แตะ

Key เป็น **Google AI Studio** (`AIza…`, endpoint `generativelanguage.googleapis.com`) — ไม่ใช่ Vertex/GCP
→ auth ง่าย แค่ `?key=<AIza>` ต่อท้าย URL หรือ header `x-goog-api-key`

## หลักการเดิมที่ต้องรักษา
- **Graceful degradation:** Gemini ล่ม/ไม่มีเน็ต/คีย์ผิด → ตกไป engine เดิม (Whisper/edge) → สุดท้าย mock
  ไม่ทำให้เว็บพัง (สไตล์เดียวกับ transcribe.py/llm.py/tts.py ทุกวันนี้)
- **เลือกด้วย env** เหมือน `TTS_ENGINE` ที่มีอยู่ — ไม่ hardcode, สลับกลับ Whisper/edge ได้ทันที
- OpenAI-compatible ใช้กับ LLM ได้ แต่ **STT/TTS ของ Gemini ไม่ใช่ OpenAI-shaped** → เรียก REST ตรง
  (ใช้ `requests` ที่มีอยู่แล้ว ไม่เพิ่ม SDK ถ้าเลี่ยงได้)

---

## ⚠️ ความเสี่ยงหลัก #1 — format ไฟล์เสียง (STT)

- frontend อัดเสียงด้วย `MediaRecorder` → ได้ **`audio/webm` (opus)** — ดูใน
  [Landing.jsx](../frontend/src/components/Landing.jsx) `new Blob(chunks,{type:'audio/webm'})`
  และ [AskDemo.jsx](../frontend/src/components/AskDemo.jsx)
- **Gemini รับ audio: wav / mp3 / aiff / aac / ogg / flac — ไม่มี webm** → ส่งดิบ = โดนปฏิเสธ

**ทางแก้ (ต้องเลือก 1):**

| ทาง | วิธี | ข้อดี | ข้อเสีย |
|---|---|---|---|
| **A. transcode ฝั่ง server** | webm→wav 16k mono ก่อนส่ง Gemini | frontend ไม่แตะ, รองรับไฟล์ประชุมทุก format ด้วย | ต้องมี ffmpeg/PyAV/pydub — **ต้องเช็คว่ามีในเครื่องไหม** |
| **B. อัด format อื่นในเบราว์เซอร์** | ลอง `audio/ogg;codecs=opus` | ไม่ต้อง transcode | Chrome ไม่รองรับ ogg (ได้แค่ webm/mp4) → พังบน Chrome |
| **C. Gemini Files API** | อัปไฟล์ผ่าน SDK ให้ Google จัดการ | robust ไฟล์ใหญ่ | เพิ่ม dep `google-genai`, ยังไม่ชัวร์ว่า transcode webm ให้ |

**เสนอ A** — transcode server-side ครอบคลุมสุด (ทั้ง live-voice webm และไฟล์ประชุม mp3/m4a)
เช็คก่อนว่า venv มี `av`(PyAV, มากับ faster-whisper) หรือ `pydub`+ffmpeg — ถ้ามีใช้ decode ในหน่วยความจำ
ถ้าไม่มี → เพิ่ม `imageio-ffmpeg` (pip ล้วน ได้ binary มาเอง ไม่ต้องลง ffmpeg ระบบ)
**[ต้องเช็คตอนลงมือ — ยังไม่ได้ verify]**

---

## STT — เพิ่มเลน Gemini ใน `transcribe.py`

env ใหม่:
```
GEMINI_API_KEY=AIza...
STT_ENGINE=gemini            # "whisper"(default เดิม) | "gemini"
GEMINI_STT_MODEL=gemini-2.5-flash    # รับ audio ได้ (audio understanding)
```

- เพิ่ม `_transcribe_gemini(path)` เป็น **ชั้นแรก** ใน `transcribe_audio()`:
  1. `STT_ENGINE=="gemini"` และมีคีย์ → transcode (ถ้าจำเป็น) → `generateContent` พร้อม
     `inline_data` (base64 wav) + prompt ไทย ("ถอดเสียงประชุมซ่อมบำรุงเป็นภาษาไทย …" ใช้ศัพท์ช่าง
     ชุดเดียวกับ `initial_prompt` เดิม ช่วยความแม่น)
  2. ล้มเหลว → `print("[STT] gemini …")` → ตกไป remote/local/mock เดิม (ไม่ throw)
- REST: `POST …/v1beta/models/{model}:generateContent?key=…`
  body `{"contents":[{"parts":[{"text":prompt},{"inline_data":{"mime_type":"audio/wav","data":b64}}]}]}`
  อ่านผล `candidates[0].content.parts[0].text`
- คืนรูปแบบเดิม (string) — endpoint `/api/transcribe` + `/api/stt` ไม่ต้องแก้
- **หมายเหตุ timestamp:** Whisper คืน `[00.5s] ...` ต่อบรรทัด; Gemini ไม่มี → คืนข้อความล้วน
  ตัวตัด timestamp ที่ [app.py:507](../backend/app.py) เป็น regex ที่ไม่เจอก็ปล่อยผ่าน → ปลอดภัย

**Trade-off ที่ต้องรู้:**
- latency: local GPU ~1-3s → Gemini คลาวด์ ~2-5s + อัปโหลดเสียง (เน็ตช้าจะนาน)
- ความแม่นไทย: Whisper large-v3 + initial_prompt ศัพท์ช่าง แม่นมาก; Gemini ดีแต่ต้องเทียบจริง
- offline: Whisper local ทำงานไม่ต้องเน็ต; Gemini ต้องเน็ต (มี fallback อยู่แล้ว)

---

## TTS — เพิ่ม engine `gemini` ใน `tts.py`

env ใหม่:
```
TTS_ENGINE=gemini            # "windows" | "edge"(เดิม) | "gemini"
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
GEMINI_TTS_VOICE=Charon      # เสียง — เลือกจาก 30 เสียง (ต้องลองหาที่พูดไทยเพราะสุด)
```

- เพิ่ม `_synthesize_gemini(text)`:
  - `generateContent` กับ tts model, `responseModalities:["AUDIO"]`,
    `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName = GEMINI_TTS_VOICE`
  - ผลเป็น **PCM base64 (24kHz mono, 16-bit)** — **ไม่ใช่ wav/mp3 พร้อมเล่น**
  - ต้อง **ห่อ PCM เป็น WAV** ด้วย `wave` (stdlib) ใส่ header ก่อนคืน → เบราว์เซอร์เล่นได้
  - คืน `(wav_bytes, "audio/wav")` เข้ากับ [tts_endpoint](../backend/app.py) เดิม
  - ล้มเหลว → `return None` → เว็บ fallback เสียงเบราว์เซอร์ (SpeechSynthesis) เหมือนเดิม
- `synthesize()` เพิ่ม branch: `TTS_ENGINE=="gemini"` → `_synthesize_gemini`

**⚠️ ความเสี่ยง #2 — เสียงไทยของ Gemini TTS:** เสียงส่วนใหญ่ปรับจูนอังกฤษ พูดไทยได้แต่สำเนียง
อาจแปร่ง ต้องลองหลายเสียง (Charon/Kore/Puck/…) เทียบกับ edge-tts Niwat ก่อนสรุป
— ถ้าสู้ edge ไม่ได้ ก็คง edge ไว้ (edge ฟรี, เสียง Neural ไทยดีอยู่แล้ว)

---

## ไฟล์ที่แก้
- `backend/transcribe.py` — `_transcribe_gemini` + transcode helper (~50-70 บรรทัด)
- `backend/tts.py` — `_synthesize_gemini` + PCM→WAV (~40 บรรทัด)
- `backend/.env.example` — เพิ่ม `GEMINI_API_KEY`, `STT_ENGINE`, `TTS_ENGINE=gemini`, model/voice
- `backend/requirements.txt` — เพิ่ม `imageio-ffmpeg` เฉพาะถ้าเครื่องไม่มี PyAV/ffmpeg (คอมเมนต์ไว้)
- (อาจ) `backend/app.py` `/api/stt-config` — โชว์ว่าตอนนี้ STT engine ไหน (ให้หน้าทดสอบเห็น)

**ไม่แตะ:** rag.py (LLM), frontend (ยังส่ง webm เหมือนเดิม, ถ้าเลือกทาง A), vault, pipeline อื่น

## Verification
1. **ไม่มีคีย์:** `STT_ENGINE=gemini` แต่ไม่ใส่ key → ต้องตกไป Whisper/mock ไม่ error (graceful)
2. **STT จริง:** อัดเสียงไทยสั้นๆ ผ่านหน้า /ask → ได้ข้อความถูก, log ไม่มี `[MOCK`, GPU ไม่ถูกใช้ (Whisper ไม่โหลด)
3. **ไฟล์ประชุม:** อัป mp3/m4a หน้า /stt → ถอดได้ (พิสูจน์ transcode ครอบ format อื่น)
4. **TTS จริง:** กดฟังคำตอบ → ได้เสียง Gemini เล่นในเบราว์เซอร์ (ไม่ fallback เสียงเบราว์เซอร์)
   → ฟังคุณภาพไทยเทียบ edge ตัดสินว่าจะใช้จริงไหม
5. **สลับกลับ:** `STT_ENGINE=whisper` / `TTS_ENGINE=edge` → กลับพฤติกรรมเดิม 100%
6. latency: จับเวลา STT/TTS เทียบ local เดิม (เผื่อคลาวด์ช้ากว่าจนกระทบ UX)

## ต้องตัดสินใจ / เช็คก่อนลงมือ
1. **[เช็ค] format:** venv มี PyAV(`av`)/ffmpeg ไหม → กำหนดวิธี transcode (ทาง A) — **ยังไม่ได้ verify**
2. **cost:** Gemini STT/TTS คิดเงินตามใช้จริง (ไม่ฟรีเหมือน Whisper local/edge) — ยอมรับได้ไหม
   สำหรับ demo ปริมาณน้อย ถูกมาก แต่ควรรู้ว่าไม่ฟรี
3. **privacy:** เสียงประชุมถูกส่งขึ้น Google cloud — ข้อมูลบริษัทโอเคไหม (Whisper local ไม่ส่งออก)
4. **TTS:** ถ้าเสียงไทย Gemini สู้ edge ไม่ได้ → คง edge ไว้ (ทำ STT อย่างเดียวก็คุ้มแล้ว เพราะ STT คือตัวกิน GPU)
