import React, { useEffect, useRef, useState } from 'react'
import { playTtsStream } from '../ttsStream.js'
import { matchNav } from '../voice/nav.js'

// ── VoiceNav — ปุ่มกดพูด (push-to-talk) ลอยทุกหน้า ────────────────────────────
// เลิกใช้ wake word (SpeechRecognition ของเบราว์เซอร์ = ส่งเสียงไป Google ตลอดตอน idle)
// เปลี่ยนเป็น "กดปุ่มค่อยฟัง" -> ไมค์เปิดเฉพาะตอนกด เสียงไป backend เรา (Whisper/OpenAI) เท่านั้น
//   กด -> อัด (VAD ตัดเองเมื่อเงียบ) -> /api/transcribe -> คำสั่งนำทาง/ถาม RAG -> ตอบ+พูด
// โชว์เฉพาะหน้าที่ไม่มี voice ของตัวเอง (home = Landing มีปุ่มไมค์เอง)

// VAD auto-endpoint (ตัดประโยคเองเมื่อเงียบ) — ค่าเดียวกับ Landing
const SILENCE_MS = 1500
const MIN_REC_MS = 500
const MAX_REC_MS = 15000
const CALIB_MS   = 350
const VAD_MARGIN = 0.020
const VAD_MIN_TH = 0.045

// home = Landing มีปุ่มไมค์ push-to-talk ของตัวเอง -> VoiceNav ไม่ต้องโชว์ซ้ำ
const OWN_VOICE_ROUTES = new Set(['home'])

export default function VoiceNav({ route, model = '' }) {
  const active = !OWN_VOICE_ROUTES.has(route)

  const [mode, setMode] = useState('idle')   // idle | listening | thinking | speaking
  const [hint, setHint] = useState('')
  const [reply, setReply] = useState('')     // คำตอบ/ผลล่าสุด (โชว์ในป้าย)

  const recRef = useRef(null)
  const streamRef = useRef(null)
  const ctxRef = useRef(null)
  const rafRef = useRef(0)
  const vadRef = useRef(null)
  const playerRef = useRef(null)
  const modelRef = useRef(model)

  useEffect(() => { modelRef.current = model }, [model])

  // ออกจากหน้าที่ active (เช่นไปหน้า home) ระหว่างอัด -> ปิดไมค์ค้าง (ไม่แตะ player ที่อาจกำลังพูด)
  useEffect(() => { if (!active) stopMeter() }, [active])
  useEffect(() => () => stopMeter(), [])   // unmount -> ปิดไมค์

  // ── อัดเสียง + VAD ตัดเองเมื่อเงียบ (ตรรกะเดียวกับ Landing) ──
  function drawMeter(analyser) {
    const buf = new Uint8Array(analyser.fftSize)
    analyser.getByteTimeDomainData(buf)
    let sum = 0
    for (let j = 0; j < buf.length; j++) { const d = (buf[j] - 128) / 128; sum += d * d }
    const level = Math.sqrt(sum / buf.length)

    const v = vadRef.current
    if (v) {
      const now = Date.now(), rec = now - v.startAt
      if (rec < CALIB_MS) {
        v.cSum += level; v.cN++; v.floor = v.cSum / v.cN
      } else {
        const th = Math.max(VAD_MIN_TH, v.floor + VAD_MARGIN)
        if (level > th) { v.started = true; v.lastLoud = now }
        else if (v.started) {
          if (now - v.lastLoud > SILENCE_MS && rec > MIN_REC_MS) { stopRec(); return }
        }
        if (rec > MAX_REC_MS) { stopRec(); return }
      }
    }
    rafRef.current = requestAnimationFrame(() => drawMeter(analyser))
  }

  function stopRec() {
    const mr = recRef.current
    if (mr && mr.state === 'recording') mr.stop()
  }

  function stopMeter() {
    cancelAnimationFrame(rafRef.current)
    vadRef.current = null
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    streamRef.current?.getTracks().forEach(s => s.stop())
    streamRef.current = null
  }

  async function record() {
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setHint('⚠️ เข้าถึงไมค์ไม่ได้ — อนุญาตไมโครโฟนในเบราว์เซอร์')
      setMode('idle')
      return
    }
    streamRef.current = stream
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    ctxRef.current = ctx
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    ctx.createMediaStreamSource(stream).connect(analyser)
    vadRef.current = { started: false, lastLoud: 0, startAt: Date.now(), floor: 0, cSum: 0, cN: 0 }
    drawMeter(analyser)

    const chunks = []
    const mr = new MediaRecorder(stream)
    recRef.current = mr
    mr.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    mr.onstop = async () => {
      stopMeter()
      setMode('thinking')
      setHint('⏳ กำลังถอดเสียง…')
      const fd = new FormData()
      fd.append('audio', new Blob(chunks, { type: 'audio/webm' }), 'q.webm')
      try {
        const res = await fetch('/api/transcribe', { method: 'POST', body: fd })
        if (!res.ok) throw new Error('stt-failed')
        const data = await res.json()
        const text = (data.text || '').trim()
        if (!text || data.is_mock) { setHint('⚠️ ไม่ได้ยินเสียง — ลองใหม่'); setMode('idle'); return }
        setHint('')
        handle(text)
      } catch (e) {
        setHint('⚠️ ถอดเสียงไม่สำเร็จ')
        setMode('idle')
      }
    }
    mr.start()
    setMode('listening')
    setHint('🎙️ พูดได้เลย — เงียบสักครู่จะตัดให้เอง')
  }

  // ถอดเสร็จ -> เป็นคำสั่งนำทาง? เปลี่ยนหน้า+พูดยืนยัน ; ไม่ใช่ -> ถาม RAG
  function handle(text) {
    const nav = matchNav(text)
    if (nav) {
      setReply('เปิด' + nav.label)
      speak('เปิด' + nav.label, () => { setMode('idle') })   // VoiceNav mount ค้าง -> เสียงไม่โดนตัด
      window.location.hash = nav.hash
      return
    }
    ask(text)
  }

  async function ask(text) {
    setMode('thinking')
    setReply('')
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, plant: '', model: modelRef.current }),
      })
      if (!res.ok) throw new Error('bad status ' + res.status)
      const data = await res.json()
      setReply(data.answer || '')
      speak(data.answer)
    } catch (e) {
      setReply('เชื่อมต่อ JARVIS ไม่ได้')
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
    const text = cleanForSpeech(raw)
    if (!text) { onDone ? onDone() : setMode('idle'); return }
    setMode('speaking')
    const backToIdle = () => { onDone ? onDone() : setMode('idle') }
    try {
      await playTtsStream(playerRef.current, text)
      backToIdle()
    } catch (e) {
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'th-TH'
      u.onend = backToIdle
      speechSynthesis.cancel()
      speechSynthesis.speak(u)
    }
  }

  // กดปุ่ม: idle -> อัด ; listening -> หยุดอัด (ไป transcribe) ; speaking -> หยุดพูด
  function onButton() {
    if (mode === 'listening') { stopRec(); return }
    if (mode === 'speaking') { playerRef.current?.pause(); speechSynthesis.cancel(); setMode('idle'); return }
    if (mode === 'idle') { setReply(''); setHint(''); record() }
    // thinking: กำลังประมวลผล -> ไม่ทำอะไร
  }

  // audio element ต้อง render ตลอด (แม้ป้ายซ่อน) เพื่อให้ playTtsStream มีที่เล่น
  const player = <audio ref={playerRef} style={{ display: 'none' }} />

  if (!active) return player   // หน้า home: Landing คุมเอง -> เงียบ แต่คง audio ไว้

  const LABELS = { idle: '🎙️ กดเพื่อพูด', listening: '⏹ กำลังฟัง… (กดหยุด)', thinking: '⏳ กำลังคิด…', speaking: '🔊 กำลังตอบ (กดหยุด)' }
  const DOT = { idle: '#46e08a', listening: '#35e0ea', thinking: '#f5a623', speaking: '#3fe9a0' }
  const busy = mode === 'thinking'

  return (
    <>
      {player}
      <div style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 60, maxWidth: 320 }} aria-live="polite">
        <button type="button" onClick={onButton} disabled={busy}
          style={{
            display: 'flex', alignItems: 'center', gap: 9, width: '100%',
            padding: '11px 16px', borderRadius: 14, cursor: busy ? 'default' : 'pointer',
            background: mode === 'listening' ? '#35e0ea' : 'rgba(12,18,28,.94)',
            color: mode === 'listening' ? '#04060a' : '#cdd8e6',
            border: '1px solid rgba(120,140,170,.3)',
            boxShadow: '0 8px 30px -8px rgba(0,0,0,.6)', backdropFilter: 'blur(6px)',
            font: '600 14px/1.3 system-ui, sans-serif', transition: 'all .15s',
          }}>
          <span style={{
            width: 9, height: 9, borderRadius: '50%', background: DOT[mode], flex: '0 0 auto',
            boxShadow: `0 0 8px ${DOT[mode]}`,
            animation: mode === 'idle' ? 'none' : 'jvpulse 1.1s ease-in-out infinite',
          }} />
          <span>{LABELS[mode]}</span>
        </button>
        {hint && <div style={{ marginTop: 6, padding: '0 4px', color: '#9fb0c4', font: '12px/1.4 system-ui', opacity: .9 }}>{hint}</div>}
        {reply && (
          <div style={{
            marginTop: 6, padding: '9px 12px', borderRadius: 12,
            background: 'rgba(12,18,28,.94)', border: '1px solid rgba(120,140,170,.24)',
            color: '#eaf2ff', font: '13px/1.5 system-ui', backdropFilter: 'blur(6px)',
          }}>{reply.slice(0, 200)}</div>
        )}
        <style>{`@keyframes jvpulse{0%,100%{opacity:.4}50%{opacity:1}}`}</style>
      </div>
    </>
  )
}
