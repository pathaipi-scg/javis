import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { forceSimulation, forceX, forceY, forceCollide } from 'd3-force'
import { playTtsStream } from '../ttsStream.js'

// หน้า Bubble Dashboard (#/dashboard) — เคสจริงจาก Obsidian vault เป็นฟอง
// ฟอง = อาการ (symptom), จัดกลุ่มตาม category, ขนาดตามความรุนแรง (severity)
// คลิกฟอง -> ขยายเต็มจอ: โชว์ Root Cause + Solution ข้าง + JARVIS ตอบ+พูดทันที

const PALETTE = ['#3e9bff', '#b15ce0', '#31c9c9', '#2ed47a', '#f2c230',
                 '#e0559b', '#8ea2b5', '#e8912f', '#5b7cfa', '#d4604a']
const R_BY_SEV = { high: 56, medium: 43, low: 32 }
const rOf = (c) => R_BY_SEV[(c.severity || '').toLowerCase()] || 40

// ตัดรหัสเคสออกก่อนอ่านเสียง (ยกจาก AskDemo)
const cleanForSpeech = (t) => (t || '')
  .replace(/\[?\(?MTN-\d+(-\d+)?\)?\]?/g, '')
  .replace(/\(\s*[,;\s]*\)/g, '').replace(/\s{2,}/g, ' ').trim()

// HUD orb แบบ J.A.R.V.I.S. — วงแหวน tick + arc ส้ม หมุนเร็วตอนกำลังคิด/พูด
function JarvisOrb({ asking, speaking }) {
  const active = asking || speaking
  return (
    <div className={'jorb' + (active ? ' on' : '')} aria-hidden="true">
      <svg viewBox="0 0 200 200">
        {/* วงนอก: ขีดสเกล + arc ส้ม */}
        <g className="jorb-r1">
          <circle cx="100" cy="100" r="88" fill="none" stroke="#39d0d8" strokeWidth="12"
                  strokeDasharray="2 7" opacity=".8" />
          <circle cx="100" cy="100" r="88" fill="none" stroke="#f5a623" strokeWidth="5"
                  strokeDasharray="34 240 12 267" strokeLinecap="round" />
        </g>
        {/* วงกลาง: ขีดถี่ + arc ส้มสั้น (หมุนสวนทาง) */}
        <g className="jorb-r2">
          <circle cx="100" cy="100" r="68" fill="none" stroke="#2b9aa8" strokeWidth="7"
                  strokeDasharray="1.5 5" opacity=".65" />
          <circle cx="100" cy="100" r="68" fill="none" stroke="#f5a623" strokeWidth="3.5"
                  strokeDasharray="18 409" strokeLinecap="round" />
        </g>
        {/* วงใน: จุดประ 2 ชั้น */}
        <g className="jorb-r3">
          <circle cx="100" cy="100" r="52" fill="none" stroke="#39d0d8" strokeWidth="1.6"
                  strokeDasharray="1 4.5" opacity=".55" />
          <circle cx="100" cy="100" r="43" fill="none" stroke="#39d0d8" strokeWidth="1.2"
                  strokeDasharray="1 6" opacity=".35" />
        </g>
      </svg>
      <div className="jorb-txt">J.A.R.V.I.S.</div>
      <div className="jorb-status">
        <i /> {asking ? 'THINKING' : speaking ? 'SPEAKING' : 'READY'}
      </div>
    </div>
  )
}

export default function BubblePage({ model = '' }) {
  const [data, setData] = useState(null)     // {groups, total, mock}
  const [plants, setPlants] = useState([])
  const [filt, setFilt] = useState({ plant: '', from: '', to: '' })
  const [dims, setDims] = useState({ w: window.innerWidth, h: window.innerHeight })
  const [nodes, setNodes] = useState([])
  const [selCats, setSelCats] = useState(new Set()) // หมวดที่เลือกจาก legend (ว่าง = ทั้งหมด)
  const [sumOpen, setSumOpen] = useState(false)     // drawer สรุปฝั่งขวา
  const [open, setOpen] = useState(null)     // เคสที่กางเต็มจอ
  const [origin, setOrigin] = useState(null) // จุดกำเนิดฟองที่คลิก {x,y,r} — ไว้เล่นอนิเมชันซูมออกจากฟอง
  const [closing, setClosing] = useState(false) // กำลังเล่นอนิเมชันหุบกลับ
  const [ans, setAns] = useState(null)       // คำตอบ JARVIS ของเคสที่เปิด
  const [asking, setAsking] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const stageRef = useRef(null)
  const playerRef = useRef(null)
  const ballRef = useRef(null)     // วงกลมใหญ่ในหน้ากาง — เป้าหมาย FLIP ของฟองที่คลิก

  // ---------- โหลดข้อมูล ----------
  useEffect(() => {
    fetch('/api/plants').then(r => r.json()).then(d => setPlants(d.plants || [])).catch(() => {})
  }, [])

  function load(f = filt) {
    const qs = new URLSearchParams()
    if (f.plant) qs.set('plant', f.plant)
    if (f.from) qs.set('from', f.from)
    if (f.to) qs.set('to', f.to)
    fetch('/api/bubbles?' + qs.toString()).then(r => r.json()).then(setData).catch(() => {})
  }
  // เปลี่ยนค่า filter -> กรองทันที ไม่ต้องกดปุ่ม
  function setFiltAndLoad(patch) {
    const next = { ...filt, ...patch }
    setFilt(next)
    load(next)
  }
  useEffect(() => { load() }, [])   // โหลดครั้งแรก

  // ---------- resize ----------
  useEffect(() => {
    const onR = () => setDims({ w: window.innerWidth, h: window.innerHeight })
    window.addEventListener('resize', onR)
    return () => window.removeEventListener('resize', onR)
  }, [])

  // สีต่อ category — อิงลำดับกลุ่มเต็ม (ไม่ใช่ชุดที่กรอง) สีจะได้นิ่งตอน filter เข้าออก
  const catColor = useMemo(() => {
    const m = {}
    ;(data?.groups || []).forEach((g, i) => { m[g.category] = PALETTE[i % PALETTE.length] })
    return m
  }, [data])

  // กลุ่มหลังกรองด้วย legend (ว่าง = โชว์หมด)
  const fGroups = useMemo(() => {
    const gs = data?.groups || []
    return selCats.size ? gs.filter(g => selCats.has(g.category)) : gs
  }, [data, selCats])

  function toggleCat(cat) {
    const next = new Set(selCats)
    next.has(cat) ? next.delete(cat) : next.add(cat)
    setSelCats(next)
  }

  // สรุปแบบ drawer: เคส (ชุดที่กรองอยู่) จัดกลุ่ม วันที่ -> หมวด, วันใหม่ก่อน
  const summary = useMemo(() => {
    const byDate = {}
    fGroups.forEach(g => g.cases.forEach(c => {
      const d = c.repair_date || 'ไม่ระบุวันที่'
      const cats = byDate[d] || (byDate[d] = {})
      ;(cats[g.category] || (cats[g.category] = [])).push(c)
    }))
    return Object.entries(byDate).sort((a, b) => b[0].localeCompare(a[0]))
      .map(([d, cats]) => [d, Object.entries(cats)])
  }, [fGroups])

  // ---------- layout ด้วย d3-force 2 ชั้น (คำนวณครั้งเดียวต่อ data/ขนาดจอ) ----------
  // ชั้น 1: วาง "จุดศูนย์กลุ่ม" — กลุ่มใหญ่กินที่มาก กระจายเต็มกลางจอ (ไม่เรียงคอลัมน์
  // เพราะกลุ่มเคสไม่เท่ากัน: กลุ่มใหญ่ล้น กลุ่มเคสเดียวลอยเดี่ยวขอบจอ)
  // ชั้น 2: ฟองเคสเกาะจุดศูนย์กลุ่มตัวเอง + collide กันเบียด
  useEffect(() => {
    if (!fGroups.length) { setNodes([]); return }
    const groups = fGroups
    // drawer สรุปเปิด = กินที่ขวา 400px -> จัดฟองในพื้นที่ที่เหลือ ไม่ให้โดนบัง
    const W = dims.w - (sumOpen ? Math.min(400, dims.w * 0.92) : 0), H = dims.h
    const top = 96, bottom = 118          // เว้นที่ header (บน) + filter bar (ล่าง)
    const cy = (top + H - bottom) / 2
    const PAD = 7                         // ช่องไฟขั้นต่ำระหว่างขอบฟอง

    // สเกลรัศมี: ถ้าพื้นที่ฟองรวมเกิน ~46% ของเวที ยังไงก็ยัดไม่ลง (ทับแน่)
    // -> ย่อทุกฟองด้วยสัดส่วนเดียวกันให้พอดีจอก่อนค่อยจัด
    const allCases = groups.flatMap(g => g.cases)
    const totArea = allCases.reduce((s, c) => { const r = rOf(c) + PAD; return s + Math.PI * r * r }, 0)
    const stageArea = W * (H - top - bottom)
    // เกิน 1 ได้: filter เหลือไม่กี่ฟอง -> ขยายกินพื้นที่จอจริงจัง (เพดาน 3.4 กันฟองเดียวล้นจอ)
    const kR = Math.min(3.4, Math.sqrt(stageArea * 0.5 / totArea))
    const rr = (c) => Math.max(27, rOf(c) * kR)   // ขั้นต่ำ 27 — ต่ำกว่านี้ตัวหนังสืออ่านไม่ออก

    // ชั้น 1: รัศมีกลุ่ม ~ พื้นที่รวมของฟองในกลุ่ม แล้วดันกันเองจนไม่ทับ
    const gnodes = groups.map((g, gi) => {
      const area = g.cases.reduce((s, c) => { const r = rr(c) + PAD; return s + r * r }, 0)
      const ang = (gi / groups.length) * Math.PI * 2
      return { gi, R: Math.sqrt(area) * 1.12,
               x: W / 2 + Math.cos(ang) * 120, y: cy + Math.sin(ang) * 60 }
    })
    const gsim = forceSimulation(gnodes)
      .force('x', forceX(W / 2).strength(0.07))
      .force('y', forceY(cy).strength(0.13))     // ดึงแนวตั้งแรงกว่า — จอกว้าง อยากให้แผ่ข้าง
      .force('collide', forceCollide(d => d.R + 6).strength(1))
      .stop()
    for (let i = 0; i < 200; i++) gsim.tick()
    gnodes.forEach(g => {
      g.x = Math.max(g.R, Math.min(W - g.R, g.x))
      g.y = Math.max(top + g.R * 0.5, Math.min(H - bottom - g.R * 0.5, g.y))
    })

    // ชั้น 2: ฟองเคสเกาะศูนย์กลุ่ม
    const raw = []
    groups.forEach((g, gi) => {
      const gc = gnodes[gi]
      g.cases.forEach((c, ci) => {
        const ang = (ci / g.cases.length) * Math.PI * 2
        raw.push({
          ...c, uid: `${gi}-${ci}`,   // key ที่ไม่ซ้ำ — case_id ในvault ซ้ำได้ (React key ซ้ำ -> ฟองซ้อน)
          cat: g.category, color: catColor[g.category],
          r: rr(c), gx: gc.x, gy: gc.y,
          x: gc.x + Math.cos(ang) * gc.R * 0.5, y: gc.y + Math.sin(ang) * gc.R * 0.5,
        })
      })
    })
    const clampAll = () => raw.forEach(d => {
      d.x = Math.max(d.r + 4, Math.min(W - d.r - 4, d.x))
      d.y = Math.max(top + d.r, Math.min(H - bottom - d.r, d.y))
    })
    const sim = forceSimulation(raw)
      .force('x', forceX(d => d.gx).strength(0.3))
      .force('y', forceY(d => d.gy).strength(0.3))
      .force('collide', forceCollide(d => d.r + PAD).strength(1).iterations(3))
      .stop()
    for (let i = 0; i < 420; i++) sim.tick()
    clampAll()
    // relaxation รอบท้าย: แยกคู่ที่ยังซ้อน (แรงดึงกลุ่ม/การ clamp ขอบจอทำให้ collide แพ้ได้)
    // ไล่ดันทีละคู่ตรงๆ จนไม่มีคู่ทับ — n~100 ฟอง O(n²)ต่อรอบ เร็วพอ ไม่ต้องพึ่ง force แล้ว
    for (let it = 0; it < 90; it++) {
      let moved = false
      for (let i = 0; i < raw.length; i++) {
        for (let j = i + 1; j < raw.length; j++) {
          const a = raw[i], b = raw[j]
          let dx = b.x - a.x, dy = b.y - a.y
          let d = Math.hypot(dx, dy)
          const min = a.r + b.r + PAD
          if (d >= min) continue
          if (d < 0.01) { dx = 1; dy = 0; d = 1 }   // ซ้อนพอดีจุดเดียว -> ดันแกน x
          const push = (min - d) / 2 / d
          a.x -= dx * push; a.y -= dy * push
          b.x += dx * push; b.y += dy * push
          moved = true
        }
      }
      clampAll()
      if (!moved) break
    }
    setNodes(raw)
  }, [fGroups, catColor, dims, sumOpen])

  // ---------- เปิดฟอง -> ซูมกางจากตำแหน่งฟอง + ถาม JARVIS ทันที ----------
  async function openBubble(c, ev) {
    // จับจุดกลางสิ่งที่คลิก (ฟอง/แถวสรุป) -> วงใหญ่ FLIP ออกจากตรงนั้น
    const el = ev.currentTarget.getBoundingClientRect()
    setOrigin({ x: el.left + el.width / 2, y: el.top + el.height / 2,
                r: Math.min(el.width, el.height) / 2 })
    setClosing(false)
    setOpen(c)
    setAns(null)
    askJarvis(c)
  }

  async function askJarvis(c) {
    if (asking) return
    setAsking(true)
    setAns(null)
    try {
      const res = await fetch('/api/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: c.symptom, plant: c.plant || filt.plant || '', model }),
      })
      if (!res.ok) throw new Error('ask-failed')
      const d = await res.json()
      setAns(d)
      speak(d.answer)             // อ่านออกเสียงทันที (คลิกฟอง = user gesture -> autoplay ผ่าน)
    } catch (e) {
      setAns({ answer: 'เชื่อมต่อ JARVIS ไม่ได้ — ตรวจว่ารัน backend ที่พอร์ต 5000 แล้ว', citations: [], error: true })
    } finally {
      setAsking(false)
    }
  }

  async function speak(text) {
    const t = cleanForSpeech(text)
    if (!t || speaking) return
    setSpeaking(true)   // ค้างไว้จนเสียง "จบ" (onended) — orb จะได้หมุนตลอดที่พูด
    try {
      await playTtsStream(playerRef.current, t)   // streaming: เสียงแรก ~1.6s (ไม่รอทั้งก้อน)
      setSpeaking(false)
    } catch (e) {
      const u = new SpeechSynthesisUtterance(t)   // fallback เสียงเบราว์เซอร์
      u.lang = 'th-TH'
      u.onend = () => setSpeaking(false)
      u.onerror = () => setSpeaking(false)
      speechSynthesis.cancel(); speechSynthesis.speak(u)
    }
  }

  // FLIP: ฟองที่คลิก "ค่อยๆ โต" ไปเป็นวงกลมใหญ่ในหน้ากาง
  // เริ่มด้วย transform ย่อ+ย้ายวงใหญ่ไปทับตำแหน่งฟองเดิม แล้วคลายเป็นตำแหน่งจริง
  useLayoutEffect(() => {
    if (!open || !origin) return
    const el = ballRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const fx = r.left + r.width / 2, fy = r.top + r.height / 2
    const s = (origin.r * 2) / r.width
    el.style.transition = 'none'
    el.style.transform = `translate(${origin.x - fx}px, ${origin.y - fy}px) scale(${s})`
    requestAnimationFrame(() => requestAnimationFrame(() => {
      el.style.transition = 'transform .68s cubic-bezier(.22,.85,.28,1)'
      el.style.transform = 'none'
    }))
  }, [open])

  function closeOpen() {
    speechSynthesis.cancel()
    try { playerRef.current?.pause() } catch (e) {}
    setSpeaking(false)   // pause ไม่ยิง onended — เคลียร์เองกัน orb หมุนค้าง
    // ย้อน FLIP: วงใหญ่หดกลับไปที่ฟองเดิม พร้อมฉากหลัง/การ์ด fade ออก แล้วค่อยถอด
    const el = ballRef.current
    if (el && origin) {
      const r = el.getBoundingClientRect()
      const fx = r.left + r.width / 2, fy = r.top + r.height / 2
      const s = (origin.r * 2) / r.width
      el.style.transition = 'transform .42s cubic-bezier(.5,0,.75,.4)'
      el.style.transform = `translate(${origin.x - fx}px, ${origin.y - fy}px) scale(${s})`
    }
    setClosing(true)
    setTimeout(() => { setOpen(null); setAns(null); setClosing(false) }, 440)
  }

  const total = data?.total ?? 0

  return (
    <div className={'bub' + (sumOpen ? ' sum-open' : '')}>
      {/* header + legend (คลิกหมวด = filter เฉพาะหมวดนั้น) */}
      <div className="bub-top">
        <a href="#/" className="bub-back">← หน้าแรก</a>
        <div className="bub-title">Bubble Dashboard <b>·</b> {total} เคส</div>
        {data?.mock && <span className="bub-mock">MOCK — vault ว่าง/อ่านไม่ได้</span>}
        <button className={'bub-sumbtn' + (sumOpen ? ' on' : '')}
          onClick={() => setSumOpen(!sumOpen)}>📋 ดูสรุป</button>
        <div className="bub-legend">
          {(data?.groups || []).map(g => (
            <button key={g.category}
              className={'bub-lg' + (selCats.size && !selCats.has(g.category) ? ' off' : '')}
              onClick={() => toggleCat(g.category)}
              title={selCats.has(g.category) ? 'คลิกเพื่อเลิกกรอง' : 'คลิกเพื่อดูเฉพาะหมวดนี้'}>
              <i style={{ background: catColor[g.category] }} />
              {g.category} <b>({g.count})</b>
            </button>
          ))}
          {selCats.size > 0 && (
            <button className="bub-lg clear" onClick={() => setSelCats(new Set())}>✕ ล้างกรอง</button>
          )}
        </div>
      </div>

      {/* เวทีฟอง */}
      <div className="bub-stage" ref={stageRef}>
        {!data && <div className="bub-loading">กำลังโหลด…</div>}
        {data && nodes.length === 0 && <div className="bub-loading">ไม่มีเคสตามที่กรอง</div>}
        {nodes.map((n) => (
          <button key={n.uid} className="bubble"
            style={{
              left: n.x - n.r, top: n.y - n.r, width: n.r * 2, height: n.r * 2,
              '--bc': n.color, fontSize: Math.max(12.5, Math.min(26, n.r / 3.4)),
              '--lines': n.r < 36 ? 2 : n.r >= 110 ? 5 : n.r >= 72 ? 4 : 3,
            }}
            title={n.symptom} onClick={(ev) => openBubble(n, ev)}>
            <span className="bubble-txt">{n.symptom}</span>
            {n.repair_date && n.r >= 36 && <span className="bubble-date">{n.repair_date}</span>}
          </button>
        ))}
      </div>

      {/* filter bar ล่าง */}
      <div className="bub-filter">
        <label>วันที่
          <input type="date" value={filt.from} onChange={e => setFiltAndLoad({ from: e.target.value })} />
        </label>
        <span className="dash">—</span>
        <label>
          <input type="date" value={filt.to} onChange={e => setFiltAndLoad({ to: e.target.value })} />
        </label>
        <label>โรงงาน
          <select value={filt.plant} onChange={e => setFiltAndLoad({ plant: e.target.value })}>
            <option value="">ทุกโรงงาน</option>
            {plants.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        {(filt.from || filt.to || filt.plant) && (
          <button className="bub-apply" onClick={() => setFiltAndLoad({ from: '', to: '', plant: '' })}>✕ ล้าง</button>
        )}
      </div>

      {/* drawer สรุปฝั่งขวา — เคสจัดกลุ่ม วันที่ -> หมวด (คลิกแถว = เปิดเคส) */}
      <aside className={'bub-sum' + (sumOpen ? ' open' : '')}>
        <div className="bub-sum-head">
          <span>📋 สรุปเคส{filt.plant ? ` — ${filt.plant}` : ''}</span>
          <button onClick={() => setSumOpen(false)}>✕</button>
        </div>
        <div className="bub-sum-body">
          {summary.length === 0 && <div className="bs-empty">ไม่มีเคสตามที่กรอง</div>}
          {summary.map(([date, cats]) => (
            <div className="bs-day" key={date}>
              <h4>📅 {date}</h4>
              {cats.map(([cat, list]) => (
                <div className="bs-cat" key={cat}>
                  <h5 style={{ color: catColor[cat] }}>{cat}</h5>
                  {list.map((c, ci) => {
                    // หัวเรื่อง = อาการ (เครื่อง ถ้ามี) ; ตก case_id ต่อเมื่อไม่มีทั้งคู่
                    const title = c.machine || c.symptom || c.case_id
                    const detailRaw = c.solution || (title === c.symptom ? '' : c.symptom) || ''
                    const detail = detailRaw.length > 64 ? detailRaw.slice(0, 64) + '…' : detailRaw
                    return (
                      <button key={c.case_id + '-' + ci} className="bs-row"
                        onClick={(ev) => openBubble({ ...c, cat }, ev)}>
                        <i style={{ background: catColor[cat] }} />
                        <span><b>{title}</b>{detail ? ` — ${detail}` : ''}</span>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* กางเต็มจอ — ฟองที่คลิกค่อยๆ โตเป็นวงใหญ่ซ้าย, เมฆ Root Cause/Solution ขวา, JARVIS ล่าง */}
      {open && (
        <div className={'bub-expand' + (closing ? ' closing' : '')}
          style={{ '--bc': catColor[open.cat] || '#3e9bff' }}>
          <button className="bub-backbtn" onClick={closeOpen}>← ย้อนกลับ</button>
          <button className="bub-close" onClick={closeOpen}>×</button>
          <div className="bx-grid">
            <div className="bx-left">
              <div className="bx-ball" ref={ballRef}>
                <span className="bx-kind">{open.cat}{open.machine ? ` · ${open.machine}` : ''}</span>
                <div className="bx-sym">{open.symptom}</div>
                <div className="bx-meta">
                  {open.case_id}{open.repair_date ? ` · ${open.repair_date}` : ''}
                  {open.plant ? ` · โรงงาน ${open.plant}` : ''}
                  {open.severity ? ` · ${open.severity}` : ''}
                </div>
              </div>
            </div>

            <div className="bx-side">
              <div className="bx-cloud cause">
                <h3>Root Cause</h3>
                <p>{open.cause || '— ไม่ระบุสาเหตุในเคส —'}</p>
              </div>
              <div className="bx-cloud sol">
                <h3>Solution</h3>
                <p>{open.solution || '— ไม่ระบุวิธีแก้ในเคส —'}</p>
              </div>
            </div>

            <div className="bx-orbcol">
              <JarvisOrb asking={asking} speaking={speaking} />
            </div>

            <div className="bx-jarvis">
              <div className="bx-jmain">
                <div className="bx-jhead">
                  <span className="live" /> JARVIS
                  {ans?.model && <span className="model-badge">🧠 {ans.model}</span>}
                  {ans?.mock && <span className="mock-badge">MOCK — ต่อ RAG ไม่ติด</span>}
                  {ans?.seconds != null && <span className="bx-time">⏱️ {ans.seconds} วิ</span>}
                  <button className="bx-replay" disabled={!ans || speaking || asking}
                    onClick={() => speak(ans?.answer)} title="ฟังซ้ำ">
                    {speaking ? '⏳' : '🔊 ฟังซ้ำ'}
                  </button>
                </div>
                <div className="bx-answer">
                  {asking && <span className="bx-thinking">กำลังคิด…</span>}
                  {!asking && ans && ans.answer}
                  {!asking && ans?.citations?.length > 0 &&
                    <div className="bx-cites">📎 อ้างอิง: {ans.citations.join(', ')}</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <audio ref={playerRef} style={{ display: 'none' }} />
    </div>
  )
}
