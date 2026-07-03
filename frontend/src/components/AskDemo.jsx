import React, { useEffect, useRef, useState } from 'react'
import { Logo, IcMic, IcStop } from './Icons.jsx'

// คำถามแนะนำ — ตรงกับเคสซ่อมบำรุงจริงใน vault
const SUGGESTIONS = [
  'มอเตอร์ปั๊มน้ำร้อนแล้วไหม้ แก้ยังไง',
  'สายพานลำเลียงขาด ต้องทำอะไรบ้าง',
  'ปั๊มมีเสียงดังและสั่น เกิดจากอะไร',
  'ไฮดรอลิกเพรสแรงดันตก แก้ยังไง',
]

const N_BARS = 24

export default function AskDemo() {
  const [q, setQ] = useState('')
  const [plant, setPlant] = useState('')
  const [plants, setPlants] = useState([])
  const [answer, setAnswer] = useState(null)   // {answer, citations, mock}
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [histOpen, setHistOpen] = useState(false)   // sidebar ประวัติ (เลื่อนเข้า/ออก)

  // ── สถานะอัดเสียง (push-to-talk) ──
  const [recording, setRecording] = useState(false)
  const [recTime, setRecTime] = useState(0)
  const [micHint, setMicHint] = useState('')
  const [speaking, setSpeaking] = useState(false)
  const recRef = useRef(null)      // MediaRecorder
  const streamRef = useRef(null)
  const ctxRef = useRef(null)      // AudioContext
  const rafRef = useRef(0)
  const timerRef = useRef(0)
  const barsRef = useRef(null)     // div ของแท่งมิเตอร์
  const playerRef = useRef(null)

  useEffect(() => {
    fetch('/api/plants').then(r => r.json()).then(d => setPlants(d.plants || [])).catch(() => {})
    loadHistory()
    return stopMeter          // ปิดไมค์ถ้า unmount กลางคัน
  }, [])

  function loadHistory() {
    fetch('/api/history').then(r => r.json()).then(d => setHistory(d.history || [])).catch(() => {})
  }

  async function ask(question, plantOverride) {
    const text = (question ?? q).trim()
    if (!text || loading) return
    setLoading(true)
    setError('')
    setAnswer(null)
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, plant: plantOverride ?? plant }),
      })
      if (!res.ok) throw new Error('bad status ' + res.status)
      setAnswer(await res.json())
      loadHistory()
    } catch (e) {
      setError('เชื่อมต่อ JARVIS ไม่ได้ — ตรวจว่ารัน backend (demo/app.py) ที่พอร์ต 5000 แล้ว')
    } finally {
      setLoading(false)
    }
  }

  // ── คลื่นเสียงจริง (Web Audio, time-domain waveform) ──
  // อ่านรูปคลื่นตรงจากไมค์ แท่งขยายจากกึ่งกลางขึ้น-ลงตามแรงสั่นของเสียง -> ดูเป็นคลื่นพูด
  function drawMeter(analyser) {
    // แถบอาจยังไม่ถูกวาด (React ยังไม่ render recbar ตอนเฟรมแรก) — ห้าม return ตาย ต้องวนรอ
    const bars = barsRef.current?.children
    if (bars && bars.length) {
      const buf = new Uint8Array(analyser.fftSize)
      analyser.getByteTimeDomainData(buf)          // 128 = เงียบ, ห่างจาก 128 = เสียงดัง
      const step = Math.floor(buf.length / N_BARS) || 1
      for (let i = 0; i < bars.length; i++) {
        let peak = 0
        for (let j = i * step; j < (i + 1) * step && j < buf.length; j++) {
          const d = Math.abs(buf[j] - 128) / 128   // 0..1 ตามแอมพลิจูดจริง
          if (d > peak) peak = d
        }
        bars[i].style.height = Math.max(10, Math.min(100, peak * 160)) + '%'
      }
    }
    rafRef.current = requestAnimationFrame(() => drawMeter(analyser))
  }

  function stopMeter() {
    cancelAnimationFrame(rafRef.current)
    clearInterval(timerRef.current)
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    streamRef.current?.getTracks().forEach(t => t.stop())   // ปิดไมค์
    streamRef.current = null
  }

  async function toggleMic() {
    // กำลังอัด -> หยุด (onstop จะส่งไปถอด)
    if (recRef.current?.state === 'recording') {
      recRef.current.stop()
      return
    }
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setMicHint('⚠️ เข้าถึงไมค์ไม่ได้ — อนุญาตไมโครโฟนในเบราว์เซอร์ก่อน')
      return
    }
    streamRef.current = stream
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    ctxRef.current = ctx
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512                      // ตัวอย่างคลื่นละเอียดขึ้น แท่งไหลลื่นขึ้น
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
      setRecording(false)
      setMicHint('⏳ กำลังถอดเสียง...')
      const fd = new FormData()
      fd.append('audio', new Blob(chunks, { type: 'audio/webm' }), 'q.webm')
      try {
        const res = await fetch('/api/transcribe', { method: 'POST', body: fd })
        if (!res.ok) throw new Error('stt-failed')
        const data = await res.json()
        setQ(data.text || '')
        const t = data.seconds != null ? ` (${data.seconds} วิ)` : ''
        setMicHint(data.is_mock
          ? `⚠️ ต่อ Whisper ไม่ได้ (ข้อความตัวอย่าง)${t} — ตรวจ/แก้ก่อนกดถาม`
          : `✅ ถอดเสร็จใน ${data.seconds} วิ — ตรวจ/แก้ข้อความแล้วกดถาม`)
      } catch (e) {
        setMicHint('⚠️ ถอดเสียงไม่สำเร็จ — พิมพ์คำถามแทนได้')
      }
    }
    mr.start()
    setRecording(true)
    setMicHint('🔴 กำลังฟัง... พูดคำถามแล้วกดหยุด')
  }

  // ── อ่านคำตอบเป็นเสียง JARVIS (edge-tts) + fallback เสียงเบราว์เซอร์ ──
  function cleanForSpeech(t) {
    // ตัดรหัสเคส (MTN-2026-0004) + วงเล็บ/ก้านที่เหลือว่าง — ให้เสียงอ่านแต่เนื้อหา
    return (t || '')
      .replace(/\[?\(?MTN-\d{4}-\d{4}\)?\]?/g, '')
      .replace(/\(\s*[,;\s]*\)/g, '')          // วงเล็บที่ว่างหลังตัดรหัส
      .replace(/\s{2,}/g, ' ')
      .trim()
  }

  async function speak() {
    const text = cleanForSpeech(answer?.answer)
    if (!text || speaking) return
    setSpeaking(true)
    try {
      const fd = new FormData()
      fd.append('text', text)
      const res = await fetch('/api/tts', { method: 'POST', body: fd })
      if (!res.ok) throw new Error('tts-unavailable')
      const player = playerRef.current
      player.src = URL.createObjectURL(await res.blob())
      await player.play()
    } catch (e) {
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'th-TH'
      speechSynthesis.cancel()
      speechSynthesis.speak(u)
    } finally {
      setSpeaking(false)
    }
  }

  async function clearHistory() {
    if (!window.confirm('ลบประวัติถาม-ตอบทั้งหมด?')) return
    await fetch('/api/history/clear', { method: 'POST' }).catch(() => {})
    setHistory([])
  }

  function onSubmit(e) {
    e.preventDefault()
    ask()
  }

  const mm = String(Math.floor(recTime / 60))
  const ss = String(recTime % 60).padStart(2, '0')

  return (
    <section className="ask ask-page" id="ask">
      <div className="ask-card">
        <div className="ask-head">
          <span className="live" /> ถาม JARVIS — ตอบจากเคสซ่อมบำรุงจริง (RAG + Typhoon)
          {plants.length > 0 && (
            <select className="ask-plant" value={plant} onChange={(e) => setPlant(e.target.value)}
                    title="ตอบจากเคสในโรงงานนี้เท่านั้น">
              <option value="">ทุกโรงงาน</option>
              {plants.map((p) => <option key={p} value={p}>โรงงาน {p}</option>)}
            </select>
          )}
        </div>

        <form className="ask-form" onSubmit={onSubmit}>
          <input
            className="ask-input"
            placeholder="เช่น “เครื่อง forming press แรงดันตก แก้ยังไง”"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="button" onClick={toggleMic} title={recording ? 'หยุดอัด' : 'กดพูดถาม'}
                  className={'ask-mic' + (recording ? ' rec' : '')}>
            {recording ? <IcStop /> : <IcMic />}
          </button>
          <button className="ask-send" type="submit" disabled={loading || !q.trim()}>
            {loading ? 'กำลังคิด…' : 'ถาม'}
          </button>
        </form>

        {recording && (
          <div className="ask-recbar">
            <span className="ask-recdot" />
            <span className="ask-rectime">{mm}:{ss}</span>
            <div className="ask-meter" ref={barsRef}>
              {Array.from({ length: N_BARS }).map((_, i) => <span key={i} className="bar" />)}
            </div>
          </div>
        )}
        {micHint && <div className="ask-hint">{micHint}</div>}

        {answer && (
          <div className="ask-answer">
            <div className="who">
              <Logo size={13} /> JARVIS
              {answer.mock && <span className="mock-badge">MOCK — ต่อ RAG ไม่ติด</span>}
              {answer.seconds != null && <span className="ask-time">⏱️ {answer.seconds} วิ</span>}
              <button type="button" className="ask-tts" onClick={speak} disabled={speaking}
                      title="ฟังคำตอบ (เสียง JARVIS)">
                {speaking ? '⏳' : '🔊 ฟังคำตอบ'}
              </button>
            </div>
            {answer.answer}
            {answer.citations?.length > 0 && (
              <div className="cites">📎 อ้างอิงจากเคส: {answer.citations.join(', ')}</div>
            )}
          </div>
        )}
        {error && (
          <div className="ask-answer" style={{ borderColor: 'rgba(255,120,120,.4)', background: 'rgba(255,90,90,.1)', color: '#ffc9c9' }}>
            {error}
          </div>
        )}

        <div className="ask-suggest">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => { setQ(s); ask(s) }}>{s}</button>
          ))}
        </div>

        <audio ref={playerRef} style={{ display: 'none' }} />
      </div>

      {/* ปุ่มแท็บเปิด/ปิด sidebar ประวัติ (ลอยขอบขวาจอ) */}
      <button type="button" className={'hist-tab' + (histOpen ? ' open' : '')}
              onClick={() => setHistOpen(!histOpen)}
              title={histOpen ? 'ซ่อนประวัติ' : 'ดูประวัติถาม-ตอบ'}>
        {histOpen ? '›' : '🕘'}
        {!histOpen && history.length > 0 && <span className="hist-count">{history.length}</span>}
      </button>

      {/* sidebar ประวัติ — เลื่อนเข้า/ออกจากขวา */}
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
                    onClick={() => { setQ(h.q); setPlant(h.plant || ''); ask(h.q, h.plant || '') }}>
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
    </section>
  )
}
