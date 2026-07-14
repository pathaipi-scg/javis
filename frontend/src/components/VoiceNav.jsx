import React, { useEffect, useRef, useState } from 'react'
import { playTtsStream } from '../ttsStream.js'
import { matchNav, SR_CLASS, WAKE_RE } from '../voice/nav.js'

// ── VoiceNav (Plan 1: ป้ายลอยฟังเสียงทุกหน้า) ──────────────────────────────
// ตัวฟังเสียงเบาๆ ที่ mount ค้างทุกหน้า ยกเว้นหน้าที่มี voice ของตัวเองอยู่แล้ว
//   - home      -> Landing มี HUD + wake ของตัวเอง (ปล่อยให้มันคุม)
//   - dashboard -> BubblePage มี orb + ถาม JARVIS ของตัวเอง (กันไมค์/เสียงชนกัน)
// หน้าอื่น (ask/case/search/stt/stats/graph): พูด "jarvis เปิด …" -> เปลี่ยนหน้า,
// หรือถามคำถาม -> ตอบ+พูด โดยไม่ต้องกลับไปหน้าแรก
//
// โค้ด engine (wake/อัด/VAD/ถอด/ถาม/พูด) จงใจ "ก๊อป" จาก Landing แบบ self-contained
// ตาม Plan 1 — ไม่แตะ Landing เลย ของเดิมจึงทำงานเหมือนเดิม 100%

// SR_CLASS + WAKE_RE ย้ายไป ../voice/nav.js (แชร์กับ Landing)

// VAD auto-endpoint (ตัดประโยคเองเมื่อเงียบ) — ค่าเดียวกับ Landing
const SILENCE_MS = 1500
const MIN_REC_MS = 500
const MAX_REC_MS = 15000
const CALIB_MS   = 350
const VAD_MARGIN = 0.020
const VAD_MIN_TH = 0.045

// คำทักตอนปลุกติด (เสียง JARVIS) — ให้รู้ว่าระบบตื่นแล้ว
const GREETINGS = [
  'สวัสดีครับ มีอะไรให้รับใช้ครับ',
  'สวัสดีครับ ให้ผมช่วยอะไรดีครับ',
  'ครับผม ว่ามาได้เลยครับ',
]

// หน้าที่ "มี voice ของตัวเอง" -> VoiceNav หยุดฟังเพื่อกันชนกัน
// home = Landing มี wake ของตัวเอง -> VoiceNav เงียบ
// dashboard เอาออก: BubblePage ไม่มี wake -> ให้ VoiceNav ฟังแทน (พูดสั่ง/กลับหน้าได้)
// (BubblePage พูดตอบเฉพาะตอนคลิกฟอง อาจมี echo เข้า wake บ้าง — ยอมรับได้)
const OWN_VOICE_ROUTES = new Set(['home'])

export default function VoiceNav({ route, model = '' }) {
  const active = !!SR_CLASS && !OWN_VOICE_ROUTES.has(route)

  const [mode, setMode] = useState('idle')   // idle | listening | thinking | speaking
  const [hint, setHint] = useState('')
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')     // คำตอบล่าสุด (โชว์ในป้ายเล็ก)

  const srRef = useRef(null)
  const recRef = useRef(null)
  const streamRef = useRef(null)
  const ctxRef = useRef(null)
  const rafRef = useRef(0)
  const timerRef = useRef(0)
  const vadRef = useRef(null)
  const playerRef = useRef(null)
  const activeRef = useRef(active)
  const modeRef = useRef('idle')
  const modelRef = useRef(model)
  const srAliveRef = useRef(0)   // เวลาที่ SR มีสัญญาณล่าสุด (heartbeat) — ใช้จับ SR ตายเงียบ

  useEffect(() => { activeRef.current = active }, [active])
  useEffect(() => { modeRef.current = mode }, [mode])
  useEffect(() => { modelRef.current = model }, [model])

  // reconcile: ฟังคำปลุกเฉพาะตอน active + ว่าง (idle) เท่านั้น
  useEffect(() => {
    if (!SR_CLASS) return
    if (active && mode === 'idle') startWake()
    else stopWake()
    // ออกจากหน้า active -> ปิดไมค์ค้าง (แต่ไม่แตะ player ที่อาจกำลังพูดยืนยัน)
    if (!active) stopMeter()
  }, [active, mode])

  useEffect(() => () => { stopWake(); stopMeter() }, [])   // unmount รวม

  // watchdog: SR ของ Chrome ตายเงียบได้ (no-speech/network/หยุดเอง) — บางทีไม่ยิง onend ด้วย
  // เลย srRef ยังไม่ null -> ค้าง. ใช้ heartbeat: ถ้า SR ไม่มีสัญญาณเกิน 5s ตอน idle -> บังคับรีสตาร์ท
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => {
      if (!wakeShouldRun()) return
      if (!srRef.current) { startWake(); return }                 // ไม่มี SR -> ปลุกใหม่
      if (Date.now() - srAliveRef.current > 5000) {               // SR ตายเงียบ -> ล้างทิ้ง+ปลุกใหม่
        stopWake(); startWake()
      }
    }, 2000)
    return () => clearInterval(id)
  }, [active])

  function wakeShouldRun() { return activeRef.current && modeRef.current === 'idle' }

  function startWake() {
    if (!SR_CLASS || srRef.current) return
    const sr = new SR_CLASS()
    sr.lang = 'th-TH'
    sr.continuous = true
    sr.interimResults = true
    const beat = () => { srAliveRef.current = Date.now() }   // heartbeat: ยืนยัน SR ยังมีชีวิต
    sr.onstart = () => { beat(); setHeard(''); setHint('🎙️ พูด “hello jarvis”') }   // ล้างคำเก่าที่ค้าง
    sr.onaudiostart = beat
    sr.onspeechstart = beat
    sr.onresult = (e) => {
      beat()
      let txt = ''
      for (let i = e.resultIndex; i < e.results.length; i++) txt += e.results[i][0].transcript
      setHeard(txt.trim().slice(-40))
      if (WAKE_RE.test(txt)) { setHeard(''); stopWake(); onWake() }
    }
    sr.onerror = () => {}   // no-speech/aborted = ปกติ; ไม่ต้องรบกวน user บนหน้าอื่น
    sr.onend = () => {
      srRef.current = null
      if (wakeShouldRun()) startWake()   // Chrome หยุดเองทุก ~60s -> ต่อใหม่
    }
    srRef.current = sr
    srAliveRef.current = Date.now()   // seed heartbeat กัน watchdog รีสตาร์ททันทีก่อน onstart
    // start() throw ได้ (เช่น InvalidStateError ตอนยังไม่หยุดสนิท) -> abort ให้สะอาด กัน SR ซ้อน
    try { sr.start() } catch { try { sr.abort() } catch (e) {} ; srRef.current = null }
  }

  function stopWake() {
    const sr = srRef.current
    srRef.current = null
    if (sr) { sr.onend = null; try { sr.abort() } catch (e) {} }
  }

  // ได้ยินคำปลุก -> ทักด้วยเสียงก่อน (ให้รู้ว่าปลุกติดแล้ว ไม่ต้องนั่งอ่านป้าย) -> ทักจบค่อยอัด
  function onWake() {
    setReply('')
    const greet = GREETINGS[Math.floor(Math.random() * GREETINGS.length)]
    setHint('👋 ' + greet)
    speak(greet, () => record())
  }

  // ── อัดเสียง + VAD ตัดเองเมื่อเงียบ (ก๊อปตรรกะจาก Landing แต่ไม่มีบาร์ HUD) ──
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
    clearInterval(timerRef.current)
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
      setHint('⚠️ เข้าถึงไมค์ไม่ได้')
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
        if (!text || data.is_mock) { setHint('⚠️ ไม่ได้ยินเสียง'); setMode('idle'); return }
        setHint('')
        handle(text)
      } catch (e) {
        setHint('⚠️ ถอดเสียงไม่สำเร็จ')
        setMode('idle')
      }
    }
    mr.start()
    setMode('listening')
  }

  // ถอดเสร็จ -> เป็นคำสั่งนำทาง? เปลี่ยนหน้า+พูดยืนยัน ; ไม่ใช่ -> ถาม RAG
  function handle(text) {
    const nav = matchNav(text)
    if (nav) {
      setReply('เปิด' + nav.label)
      // VoiceNav mount ค้าง -> พูดยืนยันได้ไม่โดนตัด (ต่างจาก Landing ตอน Plan A)
      speak('เปิด' + nav.label, () => { setMode('idle') })
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

  // audio element ต้อง render ตลอด (แม้ป้ายซ่อน) เพื่อให้ playTtsStream มีที่เล่น
  const player = <audio ref={playerRef} style={{ display: 'none' }} />

  if (!active) return player   // หน้า home/dashboard: เงียบ ไม่โชว์ป้าย แต่คง audio ไว้

  const LABELS = { idle: 'พร้อม', listening: 'กำลังฟัง', thinking: 'กำลังคิด', speaking: 'กำลังตอบ' }
  const DOT = { idle: '#46e08a', listening: '#35e0ea', thinking: '#f5a623', speaking: '#3fe9a0' }

  return (
    <>
      {player}
      <div
        aria-live="polite"
        style={{
          position: 'fixed', right: 16, bottom: 16, zIndex: 60,
          maxWidth: 320, padding: '10px 14px', borderRadius: 14,
          background: 'rgba(12,18,28,.92)', border: '1px solid rgba(120,140,170,.28)',
          boxShadow: '0 8px 30px -8px rgba(0,0,0,.6)', color: '#cdd8e6',
          font: '13px/1.4 system-ui, sans-serif', backdropFilter: 'blur(6px)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
          <span style={{
            width: 9, height: 9, borderRadius: '50%', background: DOT[mode],
            boxShadow: `0 0 8px ${DOT[mode]}`,
            animation: mode === 'idle' ? 'none' : 'jvpulse 1.1s ease-in-out infinite',
          }} />
          🎙️ JARVIS · {LABELS[mode]}
        </div>
        {hint && <div style={{ marginTop: 4, opacity: .8 }}>{hint}</div>}
        {heard && mode === 'idle' && <div style={{ marginTop: 4, opacity: .55 }}>“{heard}”</div>}
        {reply && <div style={{ marginTop: 6, color: '#eaf2ff' }}>{reply.slice(0, 160)}</div>}
        <style>{`@keyframes jvpulse{0%,100%{opacity:.4}50%{opacity:1}}`}</style>
      </div>
    </>
  )
}
