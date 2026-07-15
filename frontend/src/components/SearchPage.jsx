import React, { useEffect, useRef, useState } from 'react'

// หน้าค้นเคส — semantic search (bge-m3) จากเคสจริงใน vault

export default function SearchPage() {
  const [q, setQ] = useState('')
  const [plant, setPlant] = useState('')
  const [plants, setPlants] = useState([])
  const [data, setData] = useState(null)   // {results, tag_facet, mock}
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [histOpen, setHistOpen] = useState(false)   // sidebar ประวัติค้นหา (แบบหน้าถาม)
  const reqRef = useRef(0)   // token กัน response เก่ามาทับผลใหม่ (พิมพ์สด request ไล่กันเป็นชุด)

  useEffect(() => {
    fetch('/api/plants').then(r => r.json()).then(d => setPlants(d.plants || [])).catch(() => {})
    loadHistory()
  }, [])

  function loadHistory() {
    fetch('/api/search-history').then(r => r.json()).then(d => setHistory(d.history || [])).catch(() => {})
  }

  function clearHistory() {
    fetch('/api/search-history/clear', { method: 'POST' })
      .then(() => setHistory([]))
      .catch(() => {})
  }

  // ยิงค้นจริง — log=true บันทึกประวัติ (กดค้น/คลิกประวัติ), log=false ค้นสดขณะพิมพ์ (ไม่บันทึก)
  async function runSearch(text, pl, log) {
    text = text.trim()
    if (!text) { setData(null); setError(''); return }
    const rid = ++reqRef.current      // request ล่าสุด — ผลที่มาช้ากว่านี้จะถูกทิ้ง
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ q: text, plant: pl, log: log ? '1' : '0' })
      const res = await fetch('/api/search?' + params)
      if (!res.ok) throw new Error('bad status ' + res.status)
      const json = await res.json()
      if (rid !== reqRef.current) return   // มี request ใหม่กว่าแล้ว -> ทิ้งผลเก่า กันกระพริบ
      setData(json)
      if (log) loadHistory()               // เฉพาะค้นจริง -> รีเฟรชรายการประวัติ
    } catch (e) {
      if (rid === reqRef.current) setError('ค้นหาไม่ได้ — ตรวจว่ารัน backend (app.py) ที่พอร์ต 5000 แล้ว')
    } finally {
      if (rid === reqRef.current) setLoading(false)
    }
  }

  // กดปุ่มค้น / คลิกประวัติ -> ค้นจริง (บันทึกประวัติ)
  function search(e, qOverride, plantOverride) {
    e?.preventDefault()
    runSearch(qOverride ?? q, plantOverride ?? plant, true)
  }

  // ค้นสดขณะพิมพ์ — debounce 300ms กันยิงทุกคีย์ ; q ว่าง -> ล้างผล ; ไม่บันทึกประวัติ
  useEffect(() => {
    const text = q.trim()
    if (!text) { setData(null); return }
    const id = setTimeout(() => runSearch(text, plant, false), 300)
    return () => clearTimeout(id)
  }, [q, plant])

  return (
    <section className="case-wrap">
      <div className="case-card">
        <div className="case-head">
          <h2>🔍 ค้นเคสซ่อมบำรุง
            {data?.mock && <span className="mock-badge">MOCK — vault ว่าง/ต่อ embeddings ไม่ติด</span>}
          </h2>
          <span className="case-sub">ค้นด้วยความหมาย (semantic) — พิมพ์อาการ/เครื่อง แล้วระบบหาเคสที่ใกล้เคียงให้</span>
        </div>

        <form className="ask-form" onSubmit={search}>
          <input className="ask-input" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="เช่น แรงดันไฮดรอลิกตก / มอเตอร์ไหม้ / เสียงดังผิดปกติ" />
          {plants.length > 0 && (
            <select className="case-input search-plant" value={plant} onChange={(e) => setPlant(e.target.value)}>
              <option value="">ทุกโรงงาน</option>
              {plants.map((p) => <option key={p} value={p}>โรงงาน {p}</option>)}
            </select>
          )}
          <button className="ask-send" type="submit" disabled={loading || !q.trim()}>
            {loading ? 'กำลังค้น…' : 'ค้นหา'}
          </button>
        </form>

        {error && <div className="case-error">{error}</div>}

        {data && data.results.length === 0 && !error && (
          <div className="hist-empty">ไม่พบเคสที่เกี่ยวข้อง{plant ? ` ในโรงงาน ${plant}` : ''}</div>
        )}

        {data?.tag_facet?.length > 0 && (
          <div className="case-tags" style={{ marginTop: 16 }}>
            {data.tag_facet.map(([t, n]) => (
              <span key={t} className="case-tag on">#{t} ({n})</span>
            ))}
          </div>
        )}

        {data?.results?.map((r) => (
          <div key={r.case_id} className="sr-item">
            <div className="sr-head">
              <span className="sr-id">{r.case_id}</span>
              <span className="sr-machine">{r.machine}</span>
              {r.plant && <span className="hist-plant">โรงงาน {r.plant}</span>}
              <span className="sr-score">{r.score}%</span>
            </div>
            <div className="sr-row"><b>อาการ:</b> {r.symptom}</div>
            <div className="sr-row"><b>วิธีแก้:</b> {r.solution}</div>
            <div className="sr-tags">{r.tags.map((t) => <span key={t}>#{t}</span>)}</div>
          </div>
        ))}
      </div>

      {/* ปุ่มแท็บเปิด/ปิด sidebar ประวัติค้นหา (ลอยขอบขวาจอ — แบบเดียวกับหน้าถาม) */}
      <button type="button" className={'hist-tab' + (histOpen ? ' open' : '')}
              onClick={() => setHistOpen(!histOpen)}
              title={histOpen ? 'ซ่อนประวัติ' : 'ดูประวัติค้นหา'}>
        {histOpen ? '›' : '🕘'}
        {!histOpen && history.length > 0 && <span className="hist-count">{history.length}</span>}
      </button>

      {/* sidebar ประวัติค้นหา — เลื่อนเข้า/ออกจากขวา */}
      <aside className={'hist-drawer' + (histOpen ? ' open' : '')}>
        <div className="hist-head">
          <span>🕘 ประวัติค้นหา</span>
          <div className="hist-head-actions">
            {history.length > 0 &&
              <button type="button" className="hist-clear" onClick={clearHistory}>🗑 ล้าง</button>}
            <button type="button" className="hist-close" onClick={() => setHistOpen(false)}>✕</button>
          </div>
        </div>
        <div className="hist-body">
          {history.length === 0 && (
            <div className="hist-empty">ยังไม่มีประวัติ — ลองค้นดู แล้วรายการจะโผล่ตรงนี้ (คลิกเพื่อค้นซ้ำได้)</div>
          )}
          {history.map((h, i) => (
            <button key={i} type="button" className="hist-row" title="คลิกเพื่อค้นซ้ำ"
                    onClick={() => { setQ(h.q); setPlant(h.plant || ''); search(null, h.q, h.plant || '') }}>
              <div className="hist-q">
                {h.q}
                {h.plant && <span className="hist-plant">โรงงาน {h.plant}</span>}
                <span className="hist-t">{h.t}{h.mock ? ' · MOCK' : ''}</span>
              </div>
              <div className="hist-a">พบ {h.n} เคส</div>
              {h.top?.length > 0 && (
                <div className="hist-c">📎 {h.top.map((x) => x.case_id).join(', ')}</div>
              )}
            </button>
          ))}
        </div>
      </aside>
    </section>
  )
}
