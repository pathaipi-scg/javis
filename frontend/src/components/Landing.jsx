import React, { useEffect, useRef, useState } from 'react'
import { Logo, IcMic, IcStop } from './Icons.jsx'

// หน้าแรก = JARVIS HUD ที่ "พูดถาม-ฟังตอบ" ได้จริง (voice assistant เต็มตัว)
// flow: แตะไมค์ -> อัดเสียง (LISTENING) -> ถอด+ถาม RAG (THINKING) -> เล่นเสียงตอบ (SPEAKING) -> idle
// สถานะจริงขับสีวงแหวน HUD + ชิปโหมด; พิมพ์ถามก็ได้เผื่อไม่มีไมค์

const THEMES = {
  idle:      { ring: '#35e0ea', accent: '#f5a623', label: '#46e08a', status: 'READY',     sub: 'แตะไมค์แล้วพูดคำถามได้เลย', c: '#35e0ea' },
  listening: { ring: '#35e0ea', accent: '#f5a623', label: '#35e0ea', status: 'LISTENING', sub: 'กำลังฟัง… พูดคำถามแล้วแตะหยุด', c: '#35e0ea' },
  thinking:  { ring: '#7aa6dd', accent: '#f5a623', label: '#f5a623', status: 'THINKING',  sub: 'กำลังค้นเคส + คิดคำตอบ…',      c: '#f5a623' },
  speaking:  { ring: '#3fe9a0', accent: '#f5a623', label: '#3fe9a0', status: 'SPEAKING',  sub: 'กำลังตอบ…',                    c: '#3fe9a0' },
}
const MODE_CHIPS = ['listening', 'thinking', 'speaking']
const N_BARS = 20

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
  // model มาจาก props (dropdown อยู่บน Navbar) — Landing แค่ใช้ค่าตอนถาม

  const recRef = useRef(null)      // MediaRecorder
  const streamRef = useRef(null)
  const ctxRef = useRef(null)      // AudioContext
  const rafRef = useRef(0)
  const timerRef = useRef(0)
  const barsRef = useRef(null)
  const playerRef = useRef(null)

  useEffect(() => stopMeter, [])   // ปิดไมค์ถ้าออกจากหน้า

  const t = THEMES[mode]
  const bigTicks = ticks(56, 172, 15, t.ring, 3, 0.9, [4, 5, 17, 33], t.accent)
  const medTicks = ticks(90, 138, 7, t.ring, 1.5, 0.5, [22, 23, 61], t.accent)

  // ── มิเตอร์คลื่นเสียงจริง (time-domain) ──
  function drawMeter(analyser) {
    const bars = barsRef.current?.children
    if (bars && bars.length) {
      const buf = new Uint8Array(analyser.fftSize)
      analyser.getByteTimeDomainData(buf)
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
    rafRef.current = requestAnimationFrame(() => drawMeter(analyser))
  }

  function stopMeter() {
    cancelAnimationFrame(rafRef.current)
    clearInterval(timerRef.current)
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
      speak(data.answer)                // ได้คำตอบ -> พูดออกเสียงเลย
    } catch (e) {
      setError('เชื่อมต่อ JARVIS ไม่ได้ — ตรวจว่ารัน backend ที่พอร์ต 5000 แล้ว')
      setMode('idle')
    }
  }

  function cleanForSpeech(t) {
    return (t || '')
      .replace(/\[?\(?MTN-\d{4}-\d{4}\)?\]?/g, '')
      .replace(/\(\s*[,;\s]*\)/g, '')
      .replace(/\s{2,}/g, ' ')
      .trim()
  }

  async function speak(raw) {
    const text = cleanForSpeech(raw ?? answer?.answer)
    if (!text) { setMode('idle'); return }
    setMode('speaking')
    const backToIdle = () => setMode('idle')
    try {
      const fd = new FormData()
      fd.append('text', text)
      const res = await fetch('/api/tts', { method: 'POST', body: fd })
      if (!res.ok) throw new Error('tts-unavailable')
      const player = playerRef.current
      player.src = URL.createObjectURL(await res.blob())
      player.onended = backToIdle
      await player.play()
    } catch (e) {
      // fallback เสียงเบราว์เซอร์
      const u = new SpeechSynthesisUtterance(text)
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
      <div className="hud-sub"><span className="hud-sub-dot" />{micHint || t.sub}</div>

      {/* มิเตอร์คลื่นเสียงตอนอัด */}
      {mode === 'listening' && (
        <div className="hud-meter-row">
          <span className="hud-rectime">{mm}:{ss}</span>
          <div className="hud-meter" ref={barsRef}>
            {Array.from({ length: N_BARS }).map((_, i) => <span key={i} className="bar" style={{ background: t.ring }} />)}
          </div>
        </div>
      )}

      {/* ปุ่มไมค์ใหญ่ = แตะเพื่อพูด/หยุด */}
      <button className={'hud-mic' + (mode === 'listening' ? ' rec' : '')} onClick={toggleMic}
        style={{ borderColor: t.c, color: mode === 'listening' ? '#04060a' : t.c, background: mode === 'listening' ? t.c : hexA(t.c, 0.1), boxShadow: `0 0 26px -4px ${hexA(t.c, 0.7)}` }}>
        {mode === 'listening' ? <IcStop /> : <IcMic />}
        <span>{mode === 'listening' ? 'แตะเพื่อหยุด' : mode === 'speaking' ? 'ถามใหม่' : 'แตะเพื่อพูดถาม'}</span>
      </button>

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

      <audio ref={playerRef} style={{ display: 'none' }} />
    </section>
  )
}
