import React, { useEffect, useState } from 'react'
import { Logo } from './Icons.jsx'

// คำถามแนะนำ — ตรงกับเคสซ่อมบำรุงจริงใน vault
const SUGGESTIONS = [
  'มอเตอร์ปั๊มน้ำร้อนแล้วไหม้ แก้ยังไง',
  'สายพานลำเลียงขาด ต้องทำอะไรบ้าง',
  'ปั๊มมีเสียงดังและสั่น เกิดจากอะไร',
  'ไฮดรอลิกเพรสแรงดันตก แก้ยังไง',
]

export default function AskDemo() {
  const [q, setQ] = useState('')
  const [plant, setPlant] = useState('')
  const [plants, setPlants] = useState([])
  const [answer, setAnswer] = useState(null)   // {answer, citations, mock}
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // โหลดรายชื่อโรงงานจากเคสจริง (ไว้ทำ dropdown จำกัดขอบเขต)
  useEffect(() => {
    fetch('/api/plants')
      .then((r) => r.json())
      .then((d) => setPlants(d.plants || []))
      .catch(() => {})
  }, [])

  async function ask(question) {
    const text = (question ?? q).trim()
    if (!text || loading) return
    setLoading(true)
    setError('')
    setAnswer(null)
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, plant }),
      })
      if (!res.ok) throw new Error('bad status ' + res.status)
      setAnswer(await res.json())
    } catch (e) {
      setError('เชื่อมต่อ JARVIS ไม่ได้ — ตรวจว่ารัน backend (demo/app.py) ที่พอร์ต 5000 แล้ว')
    } finally {
      setLoading(false)
    }
  }

  function onSubmit(e) {
    e.preventDefault()
    ask()
  }

  return (
    <section className="ask" id="ask">
      <div className="ask-card">
        <div className="ask-head">
          <span className="live" /> ถาม JARVIS — ตอบจากเคสซ่อมบำรุงจริง (RAG + Typhoon)
          {plants.length > 0 && (
            <select
              className="ask-plant"
              value={plant}
              onChange={(e) => setPlant(e.target.value)}
              title="ตอบจากเคสในโรงงานนี้เท่านั้น"
            >
              <option value="">ทุกโรงงาน</option>
              {plants.map((p) => (
                <option key={p} value={p}>โรงงาน {p}</option>
              ))}
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
          <button className="ask-send" type="submit" disabled={loading || !q.trim()}>
            {loading ? 'กำลังคิด…' : 'ถาม'}
          </button>
        </form>

        {answer && (
          <div className="ask-answer">
            <div className="who">
              <Logo size={13} /> JARVIS
              {answer.mock && <span className="mock-badge">MOCK — ต่อ RAG ไม่ติด</span>}
            </div>
            {answer.answer}
            {answer.citations?.length > 0 && (
              <div className="cites">
                📎 อ้างอิงจากเคส: {answer.citations.join(', ')}
              </div>
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
      </div>
    </section>
  )
}
