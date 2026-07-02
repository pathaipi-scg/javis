import React, { useEffect, useState } from 'react'

// หน้าค้นเคส — semantic search (bge-m3) จากเคสจริงใน vault

export default function SearchPage() {
  const [q, setQ] = useState('')
  const [plant, setPlant] = useState('')
  const [plants, setPlants] = useState([])
  const [data, setData] = useState(null)   // {results, tag_facet, mock}
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/plants').then(r => r.json()).then(d => setPlants(d.plants || [])).catch(() => {})
  }, [])

  async function search(e) {
    e?.preventDefault()
    const text = q.trim()
    if (!text || loading) return
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ q: text, plant })
      const res = await fetch('/api/search?' + params)
      if (!res.ok) throw new Error('bad status ' + res.status)
      setData(await res.json())
    } catch (e) {
      setError('ค้นหาไม่ได้ — ตรวจว่ารัน backend (demo/app.py) ที่พอร์ต 5000 แล้ว')
    } finally {
      setLoading(false)
    }
  }

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
    </section>
  )
}
