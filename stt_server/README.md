# STT service (รันบน server)

แปลงเสียง → ข้อความ ด้วย faster-whisper ผ่าน HTTP ให้เครื่อง local เรียกใช้
เครื่อง local ส่งไฟล์เสียงมา → server ถอด → คืน transcript กลับไปแสดงผล/เข้า LLM (Typhoon)

## ติดตั้งบน server

```cmd
cd stt_server
copy .env.example .env        REM แล้วแก้ค่าตามต้องการ
pip install -r requirements.txt
python server.py              REM ฟังที่ 0.0.0.0:8900
```

เปิด firewall ให้เครื่อง local เข้าถึงพอร์ต 8900:

```cmd
netsh advfirewall firewall add rule name="STT 8900" dir=in action=allow protocol=TCP localport=8900
```

## ตั้งค่า (.env)

| key | ค่า | หมายเหตุ |
|-----|-----|----------|
| `WHISPER_MODEL` | `small` (CPU) → `large-v3` (GPU) | โมเดล |
| `WHISPER_DEVICE` | `cpu` → `cuda` | พอมี GPU เปลี่ยนเป็น cuda |
| `WHISPER_LANG` | `th` / `en` / `auto` | ภาษา |
| `STT_PORT` | `8900` | พอร์ต |

**พอ GPU 12GB NVIDIA มาถึง:** แก้ `.env` เป็น `WHISPER_MODEL=large-v3` + `WHISPER_DEVICE=cuda` แล้วรีสตาร์ท `server.py` — เร็วขึ้นมากและถอดแม่นขึ้น (ต้องลง CUDA/cuDNN ตามที่ faster-whisper/CTranslate2 ต้องการ)

## API

- `GET /health` → `{"status":"ok","model":...,"device":...}`
- `POST /transcribe` (multipart `file=@audio`) → `{"transcript":"[000.9s] ...","model":...,"device":...,"language":"th"}`

ตัวอย่าง:
```bash
curl -F file=@meeting.m4a http://<server-ip>:8900/transcribe
```

## เชื่อมกับ demo

ที่เครื่อง local ตั้งใน `demo/.env`:
```
STT_BASE_URL=http://<server-ip>:8900
```
ปล่อยว่าง = ถอดในเครื่อง local เหมือนเดิม (fallback)

## หมายเหตุ

- รับไฟล์ wav/m4a/mp3 ฯลฯ — faster-whisper ใช้ PyAV ที่มี ffmpeg ในตัว ไม่ต้องลง ffmpeg ระบบ
- โมเดลถูกดาวน์โหลดอัตโนมัติครั้งแรก (cache ที่ `~/.cache/huggingface`)
- โมเดลโหลดครั้งเดียวตอน startup — request ถัดมาเร็วขึ้น (ไม่โหลดซ้ำ)
