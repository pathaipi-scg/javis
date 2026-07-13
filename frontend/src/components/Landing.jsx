import React, { useEffect, useRef, useState } from 'react'
import { Logo, IcMic, IcStop } from './Icons.jsx'
import { playTtsStream } from '../ttsStream.js'

// หน้าแรก = JARVIS HUD ที่ "พูดถาม-ฟังตอบ" ได้จริง (voice assistant เต็มตัว)
// flow: แตะไมค์ -> อัดเสียง (LISTENING) -> ถอด+ถาม RAG (THINKING) -> เล่นเสียงตอบ (SPEAKING) -> idle
// สถานะจริงขับสีวงแหวน HUD + ชิปโหมด; พิมพ์ถามก็ได้เผื่อไม่มีไมค์

const THEMES = {
  idle:      { ring: '#35e0ea', accent: '#f5a623', label: '#46e08a', status: 'READY',     sub: 'แตะไมค์แล้วพูดคำถามได้เลย', c: '#35e0ea' },
  listening: { ring: '#35e0ea', accent: '#f5a623', label: '#35e0ea', status: 'LISTENING', sub: 'กำลังฟัง… พูดได้เลย เงียบสักครู่จะตัดให้เอง', c: '#35e0ea' },
  thinking:  { ring: '#7aa6dd', accent: '#f5a623', label: '#f5a623', status: 'THINKING',  sub: 'กำลังค้นเคส + คิดคำตอบ…',      c: '#f5a623' },
  speaking:  { ring: '#3fe9a0', accent: '#f5a623', label: '#3fe9a0', status: 'SPEAKING',  sub: 'กำลังตอบ…',                    c: '#3fe9a0' },
}
const MODE_CHIPS = ['listening', 'thinking', 'speaking']
const N_BARS = 20

// ── VAD auto-endpoint (ตัดประโยคเองเมื่อเงียบ ~1.5 วิ) ──
// อ่านระดับเสียงจาก AnalyserNode ที่ drawMeter ใช้อยู่แล้ว — ไม่ต้อง lib เพิ่ม, ไม่แตะ backend
const SILENCE_MS = 1500   // เงียบต่อเนื่องเท่านี้หลังเริ่มพูด = จบประโยค -> หยุดอัดเอง
const MIN_REC_MS = 500    // อัดอย่างน้อยเท่านี้ก่อนยอมตัด (กันตัดก่อนผู้ใช้เริ่มพูด)
const MAX_REC_MS = 15000  // อัดนานสุด กันค้างไม่รู้จบ
const CALIB_MS   = 350    // ช่วงคาลิเบรต noise floor ตอนเริ่มอัด (กันเสียงห้อง/เครื่องจักรหลอก)
const VAD_MARGIN = 0.020  // ต้องดังกว่า noise floor เท่านี้ถึงนับว่า "พูด"
const VAD_MIN_TH = 0.045  // เพดานล่างของ threshold (เผื่อห้องเงียบมาก floor ~0)
const CUT_HINT_MS = 400   // เงียบเกินเท่านี้ = โชว์ว่ากำลังจะตัด

// ── Wake word "hello jarvis" ──
// ใช้ webkitSpeechRecognition (Chrome/Edge) ฟังคำปลุกอย่างเดียว — ได้ยินแล้วค่อยเข้า Whisper
// รองรับเฉพาะเบราว์เซอร์ที่มี SpeechRecognition (feature-detect → ซ่อน toggle ถ้าไม่มี)
const SR_CLASS = typeof window !== 'undefined'
  ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
// ปลุกเมื่อได้ยินโทเคน "jarvis" เท่านั้น (คำทัก hello/สวัสดี เดี่ยวๆ ไม่ปลุก — พูดอย่างอื่นไม่ทำอะไร)
// SR ถอด jarvis เพี้ยนเป็นไทยได้หลายแบบ เลยครอบหลายสะกด
const WAKE_RE = /jarvis|จาร์?วิส|จาวิส|จามิส|ยาร์?วิส|จ๊า?ร?วิส/i
const GREETINGS = [
  'สวัสดีครับ มีอะไรให้รับใช้ครับ',
  'สวัสดีครับ ให้ผมช่วยอะไรดีครับ',
  'ครับผม ว่ามาได้เลยครับ',
]

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

// สร้างเส้นขีดรอบวง (ticks) — C คือจุดศูนย์กลาง viewBox 400x400
function ticks(count, r, len, color, w, o, accents, accentColor) {
  const C = 200, out = []
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2
    const c = Math.cos(a), s = Math.sin(a)
    const isA = accents.includes(i)
    out.push({
      key: i,
      x1: +(C + r * c).toFixed(2), y1: +(C + r * s).toFixed(2),
      x2: +(C + (r + len) * c).toFixed(2), y2: +(C + (r + len) * s).toFixed(2),
      color: isA ? accentColor : color, w: isA ? w + 0.8 : w, o: isA ? 1 : o,
    })
  }
  return out
}

export default function Landing({ model = '' }) {
  const [mode, setMode] = useState('idle')      // idle | listening | thinking | speaking
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState(null)     // {answer, citations, mock, seconds}
  const [error, setError] = useState('')
  const [micHint, setMicHint] = useState('')
  const [recTime, setRecTime] = useState(0)
  const [history, setHistory] = useState([])
  const [histOpen, setHistOpen] = useState(false)  // sidebar ประวัติถาม-ตอบ (log เดียวกับหน้า /ask)
  const [wakeMode, setWakeMode] = useState(false)   // toggle "ปลุกด้วยเสียง" — SR ฟังคำปลุก
  const [heard, setHeard] = useState('')            // ข้อความล่าสุดที่ SR ถอดได้ (โชว์ให้รู้ว่าฟังอยู่)
  // model มาจาก props (dropdown อยู่บน Navbar) — Landing แค่ใช้ค่าตอนถาม

  const recRef = useRef(null)      // MediaRecorder
  const streamRef = useRef(null)
  const ctxRef = useRef(null)      // AudioContext
  const rafRef = useRef(0)
  const timerRef = useRef(0)
  const barsRef = useRef(null)
  const playerRef = useRef(null)
  const srRef = useRef(null)       // SpeechRecognition (wake word)
  const wakeModeRef = useRef(false) // อ่านค่าล่าสุดใน callback ของ SR
  const modeRef = useRef('idle')
  const vadRef = useRef(null)       // สถานะ VAD ระหว่างอัด {started,lastLoud,startAt,floor,cSum,cN,cutting}
  const [cutting, setCutting] = useState(false)  // อยู่ในช่วงเงียบ กำลังจะตัด (โชว์ UX)

  useEffect(() => {
    loadHistory()
    return () => { stopMeter(); stopWake() }   // ออกจากหน้า -> ปิดไมค์ + SR
  }, [])

  // มิเรอร์ state ลง ref ให้ callback ของ SR (onend/onresult) อ่านค่าปัจจุบันได้
  useEffect(() => { wakeModeRef.current = wakeMode }, [wakeMode])
  useEffect(() => { modeRef.current = mode }, [mode])

  // reconcile: SR ควรฟังเฉพาะตอน wakeMode เปิด + ระบบว่าง (idle) เท่านั้น
  // — ตอนอัด/คิด/พูด ต้องปิด SR (กันแย่งไมค์ + กัน echo จับเสียงตอบตัวเอง)
  useEffect(() => {
    if (!SR_CLASS) return
    if (wakeMode && mode === 'idle') startWake()
    else stopWake()
  }, [wakeMode, mode])

  function wakeShouldRun() { return wakeModeRef.current && modeRef.current === 'idle' }

  function startWake() {
    if (!SR_CLASS || srRef.current) return
    const sr = new SR_CLASS()
    sr.lang = 'th-TH'
    sr.continuous = true
    sr.interimResults = true
    sr.onstart = () => setMicHint('🎙️ ฟังคำปลุกอยู่ — พูด “hello jarvis”')
    sr.onresult = (e) => {
      let txt = ''
      for (let i = e.resultIndex; i < e.results.length; i++) txt += e.results[i][0].transcript
      setHeard(txt.trim().slice(-48))    // โชว์ให้เห็นว่าฟังอยู่ + ถอดคำว่าอะไร (ไว้จูน WAKE_RE)
      if (WAKE_RE.test(txt)) { setHeard(''); stopWake(); onWake() }
    }
    sr.onerror = (ev) => {
      // ไมค์ถูกปฏิเสธ -> บอกให้อนุญาต (ไม่งั้น user นึกว่าโหมดพัง); no-speech/aborted = ปกติ ปล่อยผ่าน
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
        setMicHint('⚠️ เบราว์เซอร์ไม่ให้ใช้ไมค์ — กดอนุญาตไมโครโฟนแล้วเปิดโหมดใหม่')
        setWakeMode(false)
      }
    }
    sr.onend = () => {
      srRef.current = null
      if (wakeShouldRun()) startWake()   // Chrome หยุด SR เองทุก ~60 วิ -> ต่อใหม่ให้ฟังไม่ขาด
    }
    srRef.current = sr
    try { sr.start() } catch { srRef.current = null }
  }

  function stopWake() {
    const sr = srRef.current
    srRef.current = null
    if (sr) { sr.onend = null; try { sr.abort() } catch (e) {} }
  }

  // ได้ยินคำปลุก -> ทัก (พูด + โชว์บับเบิล) -> พอทักจบเปิดไมค์ Whisper รับคำถามจริง
  function onWake() {
    setError('')
    const greet = GREETINGS[Math.floor(Math.random() * GREETINGS.length)]
    setAnswer({ answer: greet, citations: [], greeting: true })  // โชว์คำทักเป็นบับเบิล (เห็นแม้เสียงโดน block)
    setMicHint('👋 ' + greet)
    speak(greet, () => toggleMic())      // ทักจบ -> อัดคำถาม (คำถามจริงยังผ่าน Whisper)
  }

  function loadHistory() {
    fetch('/api/history').then(r => r.json()).then(d => setHistory(d.history || [])).catch(() => {})
  }

  function clearHistory() {
    fetch('/api/history/clear', { method: 'POST' })
      .then(() => setHistory([]))
      .catch(() => {})
  }

  const t = THEMES[mode]
  const bigTicks = ticks(56, 172, 15, t.ring, 3, 0.9, [4, 5, 17, 33], t.accent)
  const medTicks = ticks(90, 138, 7, t.ring, 1.5, 0.5, [22, 23, 61], t.accent)

  // ── มิเตอร์คลื่นเสียงจริง (time-domain) + VAD ตัดเองเมื่อเงียบ ──
  function drawMeter(analyser) {
    const buf = new Uint8Array(analyser.fftSize)
    analyser.getByteTimeDomainData(buf)

    // วาดบาร์คลื่นเสียง (peak ต่อช่อง)
    const bars = barsRef.current?.children
    if (bars && bars.length) {
      const step = Math.floor(buf.length / N_BARS) || 1
      for (let i = 0; i < bars.length; i++) {
        let peak = 0
        for (let j = i * step; j < (i + 1) * step && j < buf.length; j++) {
          const d = Math.abs(buf[j] - 128) / 128
          if (d > peak) peak = d
        }
        bars[i].style.height = Math.max(8, Math.min(100, peak * 160)) + '%'
      }
    }

    // ระดับเสียงรวมของเฟรม (RMS) -> ตัดสินพูด/เงียบ
    let sum = 0
    for (let j = 0; j < buf.length; j++) { const d = (buf[j] - 128) / 128; sum += d * d }
    const level = Math.sqrt(sum / buf.length)

    const v = vadRef.current
    if (v) {
      const now = Date.now(), rec = now - v.startAt
      if (rec < CALIB_MS) {
        v.cSum += level; v.cN++; v.floor = v.cSum / v.cN   // คาลิเบรต noise floor
      } else {
        const th = Math.max(VAD_MIN_TH, v.floor + VAD_MARGIN)
        if (level > th) {                                   // ได้ยินเสียงพูด
          v.started = true; v.lastLoud = now
          if (v.cutting) { v.cutting = false; setCutting(false) }
        } else if (v.started) {                             // เงียบหลังเคยพูดแล้ว
          const silent = now - v.lastLoud
          const inCut = silent > CUT_HINT_MS
          if (inCut !== v.cutting) { v.cutting = inCut; setCutting(inCut) }
          if (silent > SILENCE_MS && rec > MIN_REC_MS) { stopRec(); return }
        }
        if (rec > MAX_REC_MS) { stopRec(); return }         // กันอัดค้าง
      }
    }
    rafRef.current = requestAnimationFrame(() => drawMeter(analyser))
  }

  // สั่งหยุดอัด (VAD/แตะปุ่ม) -> ไป mr.onstop เดิม: ถอด -> ถาม
  function stopRec() {
    const mr = recRef.current
    if (mr && mr.state === 'recording') mr.stop()
  }

  function stopMeter() {
    cancelAnimationFrame(rafRef.current)
    clearInterval(timerRef.current)
    vadRef.current = null
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    streamRef.current?.getTracks().forEach(s => s.stop())
    streamRef.current = null
  }

  async function toggleMic() {
    // กำลังอัด -> หยุด (onstop จะถอด+ถามต่อ)
    if (recRef.current?.state === 'recording') { recRef.current.stop(); return }
    // กำลังพูดตอบอยู่ -> หยุดเสียงก่อน
    if (mode === 'speaking') { playerRef.current?.pause(); speechSynthesis.cancel() }

    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setMicHint('⚠️ เข้าถึงไมค์ไม่ได้ — อนุญาตไมโครโฟนในเบราว์เซอร์ หรือพิมพ์ถามด้านล่าง')
      return
    }
    setError(''); setAnswer(null); setMicHint('')
    streamRef.current = stream
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    ctxRef.current = ctx
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    ctx.createMediaStreamSource(stream).connect(analyser)
    // เริ่มสถานะ VAD -> drawMeter จะตัดอัดเองเมื่อเงียบ
    vadRef.current = { started: false, lastLoud: 0, startAt: Date.now(), floor: 0, cSum: 0, cN: 0, cutting: false }
    setCutting(false)
    drawMeter(analyser)

    const startedAt = Date.now()
    setRecTime(0)
    timerRef.current = setInterval(() => setRecTime(Math.floor((Date.now() - startedAt) / 1000)), 250)

    const chunks = []
    const mr = new MediaRecorder(stream)
    recRef.current = mr
    mr.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    mr.onstop = async () => {
      stopMeter()
      setCutting(false)
      setMode('thinking')
      setMicHint('⏳ กำลังถอดเสียง…')
      const fd = new FormData()
      fd.append('audio', new Blob(chunks, { type: 'audio/webm' }), 'q.webm')
      try {
        const res = await fetch('/api/transcribe', { method: 'POST', body: fd })
        if (!res.ok) throw new Error('stt-failed')
        const data = await res.json()
        const text = (data.text || '').trim()
        setQ(text)
        if (!text || data.is_mock) {
          setMicHint(data.is_mock
            ? '⚠️ ต่อ Whisper ไม่ได้ — พิมพ์คำถามด้านล่างแทน'
            : '⚠️ ไม่ได้ยินเสียง — ลองพูดใหม่ หรือพิมพ์ถาม')
          setMode('idle')
          return
        }
        setMicHint('')
        ask(text)                       // ถอดเสร็จ -> ถามอัตโนมัติ (hands-free)
      } catch (e) {
        setMicHint('⚠️ ถอดเสียงไม่สำเร็จ — พิมพ์คำถามแทนได้')
        setMode('idle')
      }
    }
    mr.start()
    setMode('listening')
    setMicHint('')
  }

  // ── ถาม RAG แล้วพูดคำตอบ ──
  async function ask(question) {
    const text = (question ?? q).trim()
    if (!text) return
    setMode('thinking')
    setError(''); setAnswer(null)
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, plant: '', model }),
      })
      if (!res.ok) throw new Error('bad status ' + res.status)
      const data = await res.json()
      setAnswer(data)
      loadHistory()                     // backend log คำถามแล้ว -> รีเฟรช sidebar
      speak(data.answer)                // ได้คำตอบ -> พูดออกเสียงเลย
    } catch (e) {
      setError('เชื่อมต่อ JARVIS ไม่ได้ — ตรวจว่ารัน backend ที่พอร์ต 5000 แล้ว')
      setMode('idle')
    }
  }

  function cleanForSpeech(t) {
    return (t || '')
      .replace(/\[?\(?MTN-\d+(-\d+)?\)?\]?/g, '')
      .replace(/\(\s*[,;\s]*\)/g, '')
      .replace(/\s{2,}/g, ' ')
      .trim()
  }

  async function speak(raw, onDone) {
    const text = cleanForSpeech(raw ?? answer?.answer)
    if (!text) { onDone ? onDone() : setMode('idle'); return }
    setMode('speaking')
    // มี onDone (เช่น ทักจบ->อัดต่อ) ให้มันคุม mode เอง — ไม่แวะ idle กัน SR สตาร์ทมาชนไมค์
    const backToIdle = () => { onDone ? onDone() : setMode('idle') }
    try {
      await playTtsStream(playerRef.current, text)       // streaming: เสียงแรก ~1.6s (ไม่รอทั้งก้อน)
      backToIdle()
    } catch (e) {
      const u = new SpeechSynthesisUtterance(text)       // fallback เสียงเบราว์เซอร์
      u.lang = 'th-TH'
      u.onend = backToIdle
      speechSynthesis.cancel()
      speechSynthesis.speak(u)
    }
  }

  function onSubmit(e) {
    e.preventDefault()
    if (q.trim() && mode !== 'thinking') ask(q)
  }

  const busy = mode === 'listening' || mode === 'thinking'
  const mm = String(Math.floor(recTime / 60))
  const ss = String(recTime % 60).padStart(2, '0')

  return (
    <section className="hud-landing">
      <div className="hud-glow" style={{ background: `radial-gradient(60% 45% at 50% 34%, ${hexA(t.ring, 0.08)}, transparent 70%)` }} />

      <div className="hud-ring-wrap">
        <svg viewBox="0 0 400 400" style={{ display: 'block', width: '100%', height: '100%', filter: `drop-shadow(0 0 6px ${hexA(t.ring, 0.25)})` }}>
          <defs>
            <radialGradient id="hud-core" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={t.ring} stopOpacity="0.32" />
              <stop offset="55%" stopColor={t.ring} stopOpacity="0.07" />
              <stop offset="100%" stopColor={t.ring} stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle cx="200" cy="200" r="92" fill="url(#hud-core)" className="hud-core" />

          <g className="hud-rot" style={{ animation: 'jv-spin 44s linear infinite' }}>
            <circle cx="200" cy="200" r="186" fill="none" stroke={t.ring} strokeWidth="4" strokeLinecap="round"
              strokeDasharray="150 34 96 40 70 26 118 34 82 50" opacity="0.9" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 60s linear infinite' }}>
            {bigTicks.map(k => (
              <line key={k.key} x1={k.x1} y1={k.y1} x2={k.x2} y2={k.y2}
                stroke={k.color} strokeWidth={k.w} strokeLinecap="round" opacity={k.o} />
            ))}
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin 30s linear infinite' }}>
            <circle cx="200" cy="200" r="160" fill="none" stroke={t.ring} strokeWidth="1.5"
              strokeDasharray="60 22 40 30 90 18" opacity="0.55" />
          </g>

          <g className="hud-rot" style={{ animation: `jv-spin ${busy ? 8 : 22}s linear infinite` }}>
            <circle cx="200" cy="200" r="150" fill="none" stroke={t.accent} strokeWidth="6" strokeLinecap="round"
              strokeDasharray="150 793" strokeDashoffset="-470" style={{ filter: 'drop-shadow(0 0 5px rgba(245,166,35,.6))' }} />
            <circle cx="200" cy="200" r="150" fill="none" stroke={t.accent} strokeWidth="6" strokeLinecap="round"
              strokeDasharray="24 918" strokeDashoffset="-250" opacity="0.9" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 40s linear infinite' }}>
            {medTicks.map(k => (
              <line key={k.key} x1={k.x1} y1={k.y1} x2={k.x2} y2={k.y2}
                stroke={k.color} strokeWidth={k.w} strokeLinecap="round" opacity={k.o} />
            ))}
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin 52s linear infinite' }}>
            <circle cx="200" cy="200" r="120" fill="none" stroke={t.ring} strokeWidth="2" strokeDasharray="2 9" opacity="0.7" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 34s linear infinite' }}>
            <circle cx="200" cy="200" r="104" fill="none" stroke={t.ring} strokeWidth="1.5" strokeDasharray="1.2 7" opacity="0.5" />
          </g>

          <circle cx="200" cy="200" r="86" fill="none" stroke={t.ring} strokeWidth="1" opacity="0.35" />
        </svg>

        <div className="hud-title" style={{ textShadow: `0 0 12px ${hexA(t.ring, 0.55)}, 0 0 2px rgba(255,255,255,.7)` }}>
          J.A.R.V.I.S.
        </div>
      </div>

      <div className="hud-status">
        <span className="hud-dot" style={{ background: t.label, color: t.label }} />
        <span className="hud-status-text" style={{ color: t.label, textShadow: `0 0 10px ${hexA(t.label, 0.5)}` }}>{t.status}</span>
      </div>
      <div className="hud-sub"><span className="hud-sub-dot" />
        {micHint || (wakeMode && mode === 'idle' ? 'พูด “hello jarvis” เพื่อเริ่ม…' : t.sub)}
      </div>
      {wakeMode && mode === 'idle' && heard && (
        <div style={{ marginTop: 6, fontSize: 12, color: '#64748b', fontStyle: 'italic' }}>
          ได้ยิน: “{heard}”
        </div>
      )}

      {/* มิเตอร์คลื่นเสียงตอนอัด */}
      {mode === 'listening' && (
        <div className="hud-meter-row">
          <span className="hud-rectime">{mm}:{ss}</span>
          <div className="hud-meter" ref={barsRef}>
            {Array.from({ length: N_BARS }).map((_, i) => <span key={i} className="bar" style={{ background: cutting ? t.accent : t.ring }} />)}
          </div>
          {cutting && (
            <span style={{ fontSize: 12, fontWeight: 700, color: t.accent, letterSpacing: '.03em', whiteSpace: 'nowrap' }}>
              ✂️ ตัดอัตโนมัติ…
            </span>
          )}
        </div>
      )}

      {/* ปุ่มไมค์ใหญ่ = แตะเพื่อพูด/หยุด */}
      <button className={'hud-mic' + (mode === 'listening' ? ' rec' : '')} onClick={toggleMic}
        style={{ borderColor: t.c, color: mode === 'listening' ? '#04060a' : t.c, background: mode === 'listening' ? t.c : hexA(t.c, 0.1), boxShadow: `0 0 26px -4px ${hexA(t.c, 0.7)}` }}>
        {mode === 'listening' ? <IcStop /> : <IcMic />}
        <span>{mode === 'listening' ? 'แตะเพื่อหยุด' : mode === 'speaking' ? 'ถามใหม่' : 'แตะเพื่อพูดถาม'}</span>
      </button>

      {/* toggle ปลุกด้วยเสียง "hello jarvis" (เฉพาะ Chrome/Edge ที่มี SpeechRecognition) */}
      {SR_CLASS && (
        <button type="button" className="hud-wake" onClick={() => setWakeMode(v => !v)}
          aria-pressed={wakeMode}
          style={{
            marginTop: 14, padding: '9px 18px', borderRadius: 100, cursor: 'pointer',
            fontSize: 13, fontWeight: 600, letterSpacing: '.02em',
            border: `1px solid ${wakeMode ? hexA('#46e08a', 0.9) : 'rgba(120,140,170,.35)'}`,
            color: wakeMode ? '#04060a' : '#9fb0c4',
            background: wakeMode ? '#46e08a' : 'rgba(120,140,170,.08)',
            boxShadow: wakeMode ? '0 0 20px -4px rgba(70,224,138,.7)' : 'none',
            transition: 'all .2s',
          }}>
          {wakeMode ? '🎙️ กำลังฟัง “hello jarvis”' : '🎙️ เปิดโหมดปลุกด้วยเสียง'}
        </button>
      )}

      {/* ชิปสถานะ (สะท้อน mode ปัจจุบัน ไม่ใช่ปุ่มกด) */}
      <div className="hud-modes">
        {MODE_CHIPS.map(key => {
          const active = key === mode
          const col = THEMES[key].c
          return (
            <span key={key} className="hud-mode-chip"
              style={{
                color: active ? '#04060a' : hexA(col, 0.7),
                background: active ? col : hexA(col, 0.06),
                borderColor: active ? col : hexA(col, 0.25),
                boxShadow: active ? `0 0 16px -2px ${hexA(col, 0.7)}` : 'none',
              }}>
              {key.toUpperCase()}
            </span>
          )
        })}
      </div>

      {/* คำตอบ */}
      {answer && (
        <div className="hud-answer">
          <div className="who">
            <Logo size={13} /> JARVIS
            {answer.model && <span className="model-badge">🧠 {answer.model}</span>}
            {answer.mock && <span className="mock-badge">MOCK — ต่อ RAG ไม่ติด</span>}
            {answer.seconds != null && <span className="ask-time">⏱️ {answer.seconds} วิ</span>}
            <button type="button" className="ask-tts" onClick={() => speak()} disabled={mode === 'speaking'}
              title="ฟังคำตอบซ้ำ">{mode === 'speaking' ? '⏳' : '🔊 ฟังซ้ำ'}</button>
          </div>
          {answer.answer}
          {answer.citations?.length > 0 && (
            <div className="cites">📎 อ้างอิงจากเคส: {answer.citations.join(', ')}</div>
          )}
        </div>
      )}
      {error && <div className="hud-answer hud-answer-err">{error}</div>}

      {/* พิมพ์ถาม (เผื่อไม่มีไมค์) */}
      <form className="hud-typebar" onSubmit={onSubmit}>
        <input value={q} onChange={e => setQ(e.target.value)}
          placeholder="หรือพิมพ์คำถาม เช่น “ไฮดรอลิกเพรสแรงดันตก แก้ยังไง”" />
        <button type="submit" disabled={busy || !q.trim()}>{mode === 'thinking' ? 'กำลังคิด…' : 'ถาม'}</button>
      </form>

      <div className="hud-ctas">
        <a href="#/graph" className="hud-cta">Knowledge Graph</a>
        <a href="#/case" className="hud-cta">ป้อนเคส</a>
        <a href="#/search" className="hud-cta">ค้นเคส</a>
      </div>

      {/* ปุ่มแท็บเปิด/ปิด sidebar ประวัติ (ลอยขอบขวาจอ — ชุดเดียวกับหน้า /ask) */}
      <button type="button" className={'hist-tab' + (histOpen ? ' open' : '')}
              onClick={() => setHistOpen(!histOpen)}
              title={histOpen ? 'ซ่อนประวัติ' : 'ดูประวัติถาม-ตอบ'}>
        {histOpen ? '›' : '🕘'}
        {!histOpen && history.length > 0 && <span className="hist-count">{history.length}</span>}
      </button>

      {/* sidebar ประวัติถาม-ตอบ — เลื่อนเข้า/ออกจากขวา */}
      <aside className={'hist-drawer' + (histOpen ? ' open' : '')}>
        <div className="hist-head">
          <span>🕘 ประวัติถาม-ตอบ</span>
          <div className="hist-head-actions">
            {history.length > 0 &&
              <button type="button" className="hist-clear" onClick={clearHistory}>🗑 ล้าง</button>}
            <button type="button" className="hist-close" onClick={() => setHistOpen(false)}>✕</button>
          </div>
        </div>
        <div className="hist-body">
          {history.length === 0 && (
            <div className="hist-empty">ยังไม่มีประวัติ — ลองถามดู แล้วรายการจะโผล่ตรงนี้ (คลิกเพื่อถามซ้ำได้)</div>
          )}
          {history.map((h, i) => (
            <button key={i} type="button" className="hist-row" title="คลิกเพื่อถามซ้ำ"
                    onClick={() => { if (mode !== 'thinking') { setQ(h.q); ask(h.q) } }}>
              <div className="hist-q">
                {h.q}
                {h.plant && <span className="hist-plant">โรงงาน {h.plant}</span>}
                <span className="hist-t">{h.t}{h.mock ? ' · MOCK' : ''}</span>
              </div>
              <div className="hist-a">{h.text}</div>
              {h.citations?.length > 0 && <div className="hist-c">📎 {h.citations.join(', ')}</div>}
            </button>
          ))}
        </div>
      </aside>

      <audio ref={playerRef} style={{ display: 'none' }} />
    </section>
  )
}
