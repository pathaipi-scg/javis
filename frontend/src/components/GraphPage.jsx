import React, { useEffect, useRef, useState } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from 'd3-force'
import { zoom, zoomIdentity } from 'd3-zoom'
import { select } from 'd3-selection'

// หน้า Knowledge Graph — วาดเคสจาก Obsidian vault เป็นกราฟ (canvas + d3-force)
// ดึงข้อมูลจริงจาก /api/graph (ถ้า vault ว่างได้ mock พร้อมป้ายเตือน)

const CATS = {
  plant:     { label: 'Plants',      color: '#e8912f' },
  machine:   { label: 'Machines',    color: '#f2c230' },
  component: { label: 'Components',  color: '#3e9bff' },
  case:      { label: 'Cases',       color: '#2ed47a' },
  fault:     { label: 'Fault types', color: '#b15ce0' },
  team:      { label: 'Teams',       color: '#cdd6df' },
}
const CAUSE = new Set(['machine', 'component', 'fault']) // โหนดที่บวมตามความถี่ปัญหา

export default function GraphPage() {
  const cvRef = useRef(null)
  const G = useRef(null)              // สถานะกราฟทั้งหมด (nodes, links, sim, transform, ...)
  const [mock, setMock] = useState(false)
  const [counts, setCounts] = useState({})
  const [hiddenCats, setHiddenCats] = useState(new Set())
  const [sizeMode, setSizeMode] = useState('freq')
  const [selected, setSelected] = useState(null) // {node, neighbors}
  const [query, setQuery] = useState('')

  // ---------- โหลดข้อมูล + ตั้ง simulation ----------
  useEffect(() => {
    let dead = false
    const cv = cvRef.current
    const ctx = cv.getContext('2d')
    const DPR = Math.min(window.devicePixelRatio || 1, 2)
    const st = {
      nodes: [], links: [], adj: {}, byId: {},
      transform: zoomIdentity, hover: null, selected: null,
      hidden: new Set(), sizeMode: 'freq', W: 0, H: 0, sim: null,
    }
    G.current = st

    function resize() {
      st.W = window.innerWidth; st.H = window.innerHeight
      cv.width = st.W * DPR; cv.height = st.H * DPR
      cv.style.width = st.W + 'px'; cv.style.height = st.H + 'px'
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
      draw()
    }

    function recomputeSizes() {
      st.nodes.forEach(n => {
        if (st.sizeMode === 'freq') {
          n.metric = CAUSE.has(n.type) ? n.freq : n.deg
          n.r = CAUSE.has(n.type) ? 5 + Math.sqrt(n.freq) * 5.5 : 6
        } else {
          n.metric = n.deg
          n.r = 4 + Math.sqrt(n.deg) * 2.4
        }
        if (n.r < 4) n.r = 4
      })
    }
    st.recomputeSizes = recomputeSizes

    function draw() {
      ctx.save(); ctx.clearRect(0, 0, st.W, st.H)
      ctx.translate(st.transform.x, st.transform.y); ctx.scale(st.transform.k, st.transform.k)
      const focus = st.hover || st.selected
      const near = focus ? new Set([focus.id, ...st.adj[focus.id]]) : null

      st.links.forEach(l => {
        if (st.hidden.has(l.source.type) || st.hidden.has(l.target.type)) return
        const on = near && near.has(l.source.id) && near.has(l.target.id)
        ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y)
        ctx.strokeStyle = on ? 'rgba(49,216,221,.55)' : (near ? 'rgba(46,140,110,.06)' : 'rgba(46,150,120,.16)')
        ctx.lineWidth = on ? 1.1 : 0.6; ctx.stroke()
      })
      st.nodes.forEach(n => {
        if (st.hidden.has(n.type)) return
        const dim = near && !near.has(n.id)
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832)
        ctx.globalAlpha = dim ? 0.18 : 1
        ctx.shadowColor = n.color; ctx.shadowBlur = dim ? 0 : (n.metric > 3 ? 16 : 8)
        ctx.fillStyle = n.color; ctx.fill(); ctx.shadowBlur = 0
        if (st.selected && st.selected.id === n.id) { ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke() }
        ctx.globalAlpha = 1
      })
      // ป้ายชื่อ: hub ใหญ่ + โหนดรอบตัวที่โฟกัส
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      const labelMin = st.sizeMode === 'freq' ? 3 : 4
      st.nodes.forEach(n => {
        if (st.hidden.has(n.type)) return
        const show = n.metric >= labelMin || (near && near.has(n.id)) || (st.selected && st.selected.id === n.id)
        if (!show) return
        const dim = near && !near.has(n.id)
        ctx.globalAlpha = dim ? 0.25 : 1
        ctx.font = `${Math.max(10, Math.min(16, 9 + n.metric * 0.55))}px 'Anuphan', sans-serif`
        ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fillText(n.id, n.x + 0.6, n.y + n.r + 9 + 0.6)
        ctx.fillStyle = '#e8edf2'; ctx.fillText(n.id, n.x, n.y + n.r + 9)
        ctx.globalAlpha = 1
      })
      ctx.restore()
    }
    st.draw = draw

    function nodeAt(mx, my) {
      const x = (mx - st.transform.x) / st.transform.k
      const y = (my - st.transform.y) / st.transform.k
      let best = null, bd = 1e9
      st.nodes.forEach(n => {
        if (st.hidden.has(n.type)) return
        const d = Math.hypot(n.x - x, n.y - y)
        if (d < n.r + 4 && d < bd) { bd = d; best = n }
      })
      return best
    }

    st.openNode = (n) => {
      st.selected = n
      const neighbors = [...st.adj[n.id]].map(id => st.byId[id]).sort((a, b) => b.deg - a.deg)
      setSelected({ node: n, neighbors })
      draw()
    }
    st.centerOn = (n) => {
      const k = Math.max(st.transform.k, 1.1)
      st.transform = zoomIdentity.translate(st.W / 2 - n.x * k, st.H / 2 - n.y * k).scale(k)
      select(cv).call(st.zoomBehavior.transform, st.transform)
      draw()
    }

    resize()
    window.addEventListener('resize', resize)

    st.zoomBehavior = zoom().scaleExtent([0.25, 5]).on('zoom', e => { st.transform = e.transform; draw() })
    select(cv).call(st.zoomBehavior)

    const onMove = e => {
      const n = nodeAt(e.clientX, e.clientY)
      if (n !== st.hover) { st.hover = n; cv.style.cursor = n ? 'pointer' : 'grab'; draw() }
    }
    const onClick = e => { const n = nodeAt(e.clientX, e.clientY); if (n) st.openNode(n) }
    cv.addEventListener('mousemove', onMove)
    cv.addEventListener('click', onClick)

    fetch('/api/graph').then(r => r.json()).then(data => {
      if (dead) return
      setMock(data.mock)
      const nodes = data.nodes
      const idset = new Set(nodes.map(n => n.id))
      const links = data.links.filter(l => idset.has(l.source) && idset.has(l.target))
      const byId = Object.fromEntries(nodes.map(n => [n.id, n]))

      // degree + ความถี่ (จำนวนเคสที่แตะโหนดนั้น)
      const deg = {}, caseFreq = {}
      links.forEach(l => {
        deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1
        if (byId[l.source].type === 'case') caseFreq[l.target] = (caseFreq[l.target] || 0) + 1
        if (byId[l.target].type === 'case') caseFreq[l.source] = (caseFreq[l.source] || 0) + 1
      })
      nodes.forEach(n => {
        n.deg = deg[n.id] || 0
        n.color = (CATS[n.type] || CATS.team).color
        n.freq = n.type === 'case' ? 1 : (caseFreq[n.id] || 0)
      })
      // โรงงานรวมความถี่จากเครื่องในสังกัด
      nodes.filter(n => n.type === 'plant').forEach(p => {
        let s = 0
        links.forEach(l => {
          if (l.source === p.id && byId[l.target].type === 'machine') s += byId[l.target].freq
          if (l.target === p.id && byId[l.source].type === 'machine') s += byId[l.source].freq
        })
        p.freq = s
      })

      st.nodes = nodes; st.links = links; st.byId = byId
      st.adj = {}; nodes.forEach(n => st.adj[n.id] = new Set())
      links.forEach(l => { st.adj[l.source].add(l.target); st.adj[l.target].add(l.source) })
      recomputeSizes()

      const c = {}; nodes.forEach(n => c[n.type] = (c[n.type] || 0) + 1)
      setCounts(c)

      st.sim = forceSimulation(nodes)
        .force('link', forceLink(links).id(d => d.id).distance(46).strength(0.28))
        .force('charge', forceManyBody().strength(-105))
        .force('center', forceCenter(st.W / 2, st.H / 2))
        // แรงดึงกลับกลางจออ่อนๆ — กันก้อนกราฟที่ไม่เชื่อมกันถูก charge ผลักห่างสะสม
        // ทุกครั้งที่ restart (สลับโหมดขนาด) จนหลุดจอ
        .force('x', forceX(st.W / 2).strength(0.05))
        .force('y', forceY(st.H / 2).strength(0.07))
        .force('collide', forceCollide().radius(d => d.r + 3))
        .on('tick', draw)
      st.transform = zoomIdentity.translate(st.W * 0.06, 0).scale(0.82)
      select(cv).call(st.zoomBehavior.transform, st.transform)
      st.sim.alpha(0.9).restart()
    }).catch(() => {})

    return () => {
      dead = true
      window.removeEventListener('resize', resize)
      cv.removeEventListener('mousemove', onMove)
      cv.removeEventListener('click', onClick)
      if (st.sim) st.sim.stop()
    }
  }, [])

  // ---------- ควบคุมจาก UI (legend / โหมดขนาด / ค้นหา) ----------
  const toggleCat = (k) => {
    const st = G.current
    const next = new Set(hiddenCats)
    next.has(k) ? next.delete(k) : next.add(k)
    setHiddenCats(next)
    st.hidden = next
    st.draw()
  }

  const switchMode = (m) => {
    if (m === sizeMode) return
    setSizeMode(m)
    const st = G.current
    st.sizeMode = m
    st.recomputeSizes()
    if (st.sim) {
      st.sim.force('collide', forceCollide().radius(d => d.r + 3))
      st.sim.alpha(0.55).restart()
    }
    st.draw()
  }

  const onSearch = (v) => {
    setQuery(v)
    const st = G.current
    const q = v.trim().toLowerCase()
    if (!q) { st.hover = null; st.draw(); return }
    const hit = st.nodes.find(n => n.id.toLowerCase().includes(q))
    if (hit) { st.hover = hit; st.draw() }
  }
  const onSearchEnter = (e) => {
    if (e.key !== 'Enter') return
    const st = G.current
    const q = query.trim().toLowerCase()
    const hit = st.nodes.find(n => n.id.toLowerCase().includes(q))
    if (hit) { st.centerOn(hit); st.openNode(hit) }
  }

  const openById = (id) => {
    const st = G.current
    const n = st.byId[id]
    if (n) { st.centerOn(n); st.openNode(n) }
  }
  const closePanel = () => {
    setSelected(null)
    const st = G.current
    st.selected = null
    st.draw()
  }

  const selCat = selected ? (CATS[selected.node.type] || CATS.team) : null

  return (
    <div className="gp">
      <canvas ref={cvRef} className="gp-canvas" />

      <div className="gp-topbar">
        <a href="#/" className="gp-back">← หน้าแรก</a>
        <div className="gp-brand">J·A·R·V·I·S <b>·</b> Second Brain</div>
        {mock && <span className="gp-mock">MOCK — vault ว่าง/อ่านไม่ได้</span>}
        <div className="gp-modes">
          <button className={sizeMode === 'freq' ? 'on' : ''} onClick={() => switchMode('freq')}>◉ ความถี่ปัญหา</button>
          <button className={sizeMode === 'deg' ? 'on' : ''} onClick={() => switchMode('deg')}>◇ การเชื่อม</button>
        </div>
        <div className="gp-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8b96a3" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <input value={query} placeholder="ค้นหาโหนด… (เช่น เครื่อง, hydraulic)"
            onChange={e => onSearch(e.target.value)} onKeyDown={onSearchEnter} />
        </div>
      </div>

      <div className="gp-legend">
        <h4>Categories</h4>
        {Object.entries(CATS).map(([k, c]) => (
          <div key={k} className={`gp-lg ${hiddenCats.has(k) ? 'off' : ''}`} onClick={() => toggleCat(k)}>
            <span className="dot" style={{ color: c.color, background: c.color }} />
            <span className="nm">{c.label}</span>
            <span className="ct">{counts[k] || 0}</span>
          </div>
        ))}
      </div>

      <div className={`gp-panel ${selected ? 'open' : ''}`}>
        <button className="close" onClick={closePanel}>×</button>
        {selected && (
          <>
            <span className="kind" style={{ background: selCat.color + '22', color: selCat.color }}>
              {selCat.label.replace(/s$/, '')}
            </span>
            <h2>{selected.node.id}</h2>
            <div className="meta">
              {selected.node.type === 'case' ? '1 event' : `${selected.node.freq} cases`} · {selected.node.deg} links
            </div>
            {selected.node.body && (<><div className="sec">Note</div><div className="body">{selected.node.body}</div></>)}
            <div className="sec">Linked ({selected.neighbors.length})</div>
            {selected.neighbors.map(x => {
              const cc = CATS[x.type] || CATS.team
              return (
                <div key={x.id} className="lk" onClick={() => openById(x.id)}>
                  <span className="dot" style={{ color: cc.color, background: cc.color }} />
                  <span>{x.id}</span>
                </div>
              )
            })}
          </>
        )}
      </div>

      <div className="gp-hint">scroll = zoom · drag = pan · click node = open</div>
    </div>
  )
}
