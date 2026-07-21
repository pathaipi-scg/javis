import React, { useEffect, useState } from 'react'
import { getToken } from '../auth'

// หน้า KM — อัปโหลดเอกสาร (Word/PDF/PPT/Excel) เข้า vault, แปลงทุกหน้าเป็น PNG,
// แล้วกด Train ให้ AI วิเคราะห์ทีละหน้า + สร้างบทสรุป (เข้า index เดียวกับเคส -> ถามที่หน้าแรกเจอ)
// สมองอยู่ backend: /api/km/folders, /api/km/upload, /api/km/list, /api/km/train, /api/km/asset

// โหนดโฟลเดอร์ (recursive) — คลิกเพื่อเลือกเป็นที่เก็บ
function TreeNode({ node, selected, onSelect, depth }) {
  const [open, setOpen] = useState(depth < 1)
  const has = node.children && node.children.length > 0
  return (
    <div>
      <div className={'km-tree-row' + (selected === node.path ? ' on' : '')}
           style={{ paddingLeft: 8 + depth * 14 }}>
        <span className="km-tree-tw" onClick={() => has && setOpen(o => !o)}>
          {has ? (open ? '▾' : '▸') : '·'}
        </span>
        <span className="km-tree-name" onClick={() => onSelect(node.path)}>📁 {node.name}</span>
      </div>
      {has && open && node.children.map(c =>
        <TreeNode key={c.path} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />)}
    </div>
  )
}

export default function KmPage() {
  const [tree, setTree] = useState([])
  const [target, setTarget] = useState('')      // path โฟลเดอร์ที่เลือก
  const [files, setFiles] = useState([])         // File[] ที่จะอัปโหลด
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [docs, setDocs] = useState([])
  const [picked, setPicked] = useState({})       // km_id -> bool (เลือก train)
  const [progress, setProgress] = useState(null)  // {km_id, i, n} ระหว่าง train
  const [showTrain, setShowTrain] = useState(false)  // เปิด modal เลือกไฟล์ train
  const [upPct, setUpPct] = useState(null)  // % อัปโหลด (0-100) | -1 = แปลงฝั่ง server (indeterminate)

  function openTrain() {
    // เปิด modal + default ติ๊กเฉพาะที่ยังไม่เทรน
    const init = {}
    docs.filter(d => d.png_count > 0 && d.training_status !== 'Trained').forEach(d => { init[d.km_id] = true })
    setPicked(init); setShowTrain(true)
  }

  function loadTree() { fetch('/api/km/folders').then(r => r.json()).then(d => setTree(d.tree || [])).catch(() => {}) }
  function loadDocs() { fetch('/api/km/list').then(r => r.json()).then(d => setDocs(d.docs || [])).catch(() => {}) }
  useEffect(() => { loadTree(); loadDocs() }, [])

  async function newFolder() {
    const name = window.prompt('ชื่อโฟลเดอร์ใหม่ (วางใต้ ' + (target || 'ราก vault') + ')')
    if (!name) return
    const path = target ? target + '/' + name.trim() : name.trim()
    const res = await fetch('/api/km/folders', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    if (res.ok) { const d = await res.json(); setTarget(d.path); loadTree() }
  }

  async function doUpload(e) {
    e.preventDefault()
    if (busy || !files.length) return
    if (!target) { setMsg('เลือกโฟลเดอร์ปลายทางก่อน'); return }
    setBusy(true); setMsg(''); setUpPct(0)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('file', f))
      fd.append('targetPath', target)
      // ใช้ XHR แทน fetch — fetch อ่าน % อัปโหลดไม่ได้ (ไม่มี upload.onprogress)
      const d = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', '/api/km/upload')
        // XHR ไม่ผ่าน window.fetch ที่ถูกดักใน auth.js -> ต้องแนบ token เอง ไม่งั้น 401
        const tok = getToken()
        if (tok) xhr.setRequestHeader('Authorization', 'Bearer ' + tok)
        // ไบต์ขึ้นไปเรื่อย ๆ = แถบเต็ม; ครบ 100% = server เริ่มแปลงเป็นรูป -> สลับเป็น indeterminate
        xhr.upload.onprogress = (ev) => {
          if (!ev.lengthComputable) return
          const p = Math.round(ev.loaded / ev.total * 100)
          setUpPct(p >= 100 ? -1 : p)
        }
        xhr.upload.onload = () => setUpPct(-1)   // ส่งครบแล้ว รอ server แปลง
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText)) } catch (err) { reject(err) }
          } else reject(new Error('HTTP ' + xhr.status))
        }
        xhr.onerror = () => reject(new Error('network'))
        xhr.send(fd)
      })
      const ok = (d.results || []).filter(r => r.ok).length
      const bad = (d.results || []).filter(r => !r.ok)
      setMsg(`อัปโหลด/แปลงเสร็จ ${ok} ไฟล์` + (bad.length ? ` — ล้มเหลว ${bad.length} (ตรวจว่าลง LibreOffice แล้วสำหรับไฟล์ Office)` : ''))
      setFiles([])
      loadDocs()
    } catch {
      setMsg('อัปโหลดไม่สำเร็จ — ตรวจ backend + VAULT_PATH')
    } finally { setBusy(false); setUpPct(null) }
  }

  async function doTrain() {
    const ids = Object.keys(picked).filter(k => picked[k])
    if (!ids.length || busy) return
    setBusy(true); setMsg(''); setProgress({ km_id: '', i: 0, n: 0 })
    try {
      const res = await fetch('/api/km/train', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ km_ids: ids }),
      })
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop()
        for (const line of lines) {
          if (!line.trim()) continue
          const ev = JSON.parse(line)
          if (ev.type === 'start') setProgress({ km_id: ev.km_id, i: 0, n: ev.slides })
          else if (ev.type === 'slide') setProgress({ km_id: ev.km_id, i: ev.i, n: ev.n })
          else if (ev.type === 'done') setMsg(m => m + `\n✅ ${ev.km_id}: ${ev.slides} หน้า` + (ev.cases ? `, แตก ${ev.cases} เคส` : ''))
        }
      }
      setProgress(null); setPicked({}); setShowTrain(false); loadDocs()
      setMsg(m => (m + '\nเทรนเสร็จ — ถามที่หน้าแรกได้เลย (บทสรุปเข้า index แล้ว)').trim())
    } catch {
      setMsg('เทรนไม่สำเร็จ — ตรวจ Azure ใน .env (vision ต้องพร้อม)')
      setProgress(null)
    } finally { setBusy(false) }
  }

  // โชว์เฉพาะที่แปลงรูปแล้วและยังไม่เทรน (เทรนแล้วไม่ต้องขึ้นซ้ำ)
  const trainable = docs.filter(d => d.png_count > 0 && d.training_status !== 'Trained')
  return (
    <section className="case-wrap km-wrap">
      <div className="case-card">
        <div className="case-head">
          <h2>📚 คลังความรู้ (KM) — อัปโหลดเอกสาร</h2>
          <span className="case-sub">อัปโหลด Word / PDF / PPT / Excel → แปลงทุกหน้าเป็นรูป → กด Train ให้ AI สรุป (ถามที่หน้าแรกได้)</span>
        </div>

        <div className="km-cols">
          {/* ── ซ้าย: เลือกโฟลเดอร์ ── */}
          <div className="km-tree">
            <div className="km-tree-head">
              <span>ที่เก็บใน vault</span>
              <button type="button" className="btn-ghost" onClick={newFolder}>+ โฟลเดอร์</button>
            </div>
            <div className={'km-tree-row' + (target === '' ? ' on' : '')} style={{ paddingLeft: 8 }}>
              <span className="km-tree-tw">·</span>
              <span className="km-tree-name" onClick={() => setTarget('')}>📁 (ราก vault)</span>
            </div>
            {tree.map(n => <TreeNode key={n.path} node={n} selected={target} onSelect={setTarget} depth={0} />)}
          </div>

          {/* ── ขวา: ฟอร์มอัปโหลด ── */}
          <form className="km-form" onSubmit={doUpload}>
            <div className="km-target">ปลายทาง: <b>{target || '(ราก vault)'}</b></div>
            <label>เลือกไฟล์ (เลือกหลายไฟล์ได้)</label>
            <input className="case-file" type="file" multiple
                   accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx"
                   onChange={e => setFiles([...e.target.files])} />
            {files.length > 0 && <div className="km-files">{files.map(f => f.name).join(', ')}</div>}
            <div className="km-hint">อัปโหลดเข้าโฟลเดอร์ที่ชื่อมีคำว่า “Morning” → ตอน Train จะแตกเป็นเคส MTN เข้า cases/ ให้อัตโนมัติ</div>
            <div className="case-actions km-actions">
              <button className="btn-save" type="submit" disabled={busy || !files.length}>
                {busy ? '⏳ กำลังอัปโหลด/แปลง…' : '⬆ อัปโหลด + แปลงเป็นรูป'}
              </button>
              <button type="button" className="btn-save" onClick={openTrain} disabled={busy || trainable.length === 0}>
                🚀 Train เอกสาร{trainable.length > 0 ? ` (${trainable.length})` : ''}
              </button>
            </div>
            <div className="km-count">
              ในคลัง {docs.length} ไฟล์ · เทรนแล้ว {docs.filter(d => d.training_status === 'Trained').length} · รอเทรน {trainable.length}
            </div>
            {upPct !== null && (
              <div className="km-prog">
                <div className="km-prog-lbl">
                  {upPct < 0 ? 'กำลังแปลงเป็นรูปที่ server…' : `กำลังอัปโหลด ${upPct}%`}
                </div>
                <div className={'km-bar' + (upPct < 0 ? ' indet' : '')}>
                  <div className="km-bar-fill" style={{ width: upPct < 0 ? '100%' : upPct + '%' }} />
                </div>
              </div>
            )}
          </form>
        </div>
        {msg && <pre className="km-msg">{msg}</pre>}
      </div>

      {/* ── Modal เลือกไฟล์ Train ── */}
      {showTrain && (
        <div className="km-modal-back" onClick={() => !busy && setShowTrain(false)}>
          <div className="km-modal" onClick={e => e.stopPropagation()}>
            <div className="km-modal-head">
              <h3>🚀 Train เอกสาร KM</h3>
              <span>ส่งรูปแต่ละหน้าเข้า AI (Azure) วิเคราะห์ + สร้างบทสรุป · โฟลเดอร์ที่มี “Morning” จะแตกเป็นเคส MTN ด้วย</span>
            </div>
            <div className="km-modal-table">
              <div className="km-mt-head">
                <span className="km-mt-ck">
                  <input type="checkbox" disabled={busy}
                         checked={trainable.length > 0 && trainable.every(d => picked[d.km_id])}
                         onChange={e => {
                           const v = e.target.checked; const n = {}
                           trainable.forEach(d => { n[d.km_id] = v }); setPicked(n)
                         }} />
                </span>
                <span className="km-mt-file">ไฟล์</span>
                <span className="km-mt-path">ที่เก็บ</span>
                <span className="km-mt-n">หน้า</span>
                <span className="km-mt-st">สถานะ</span>
              </div>
              <div className="km-mt-body">
                {trainable.map(d => (
                  <label key={d.km_id} className="km-mt-row">
                    <span className="km-mt-ck">
                      <input type="checkbox" checked={!!picked[d.km_id]} disabled={busy}
                             onChange={e => setPicked(p => ({ ...p, [d.km_id]: e.target.checked }))} />
                    </span>
                    <span className="km-mt-file" title={d.source_file}>{d.source_file || d.km_id}</span>
                    <span className="km-mt-path" title={d.folder}>{d.folder}</span>
                    <span className="km-mt-n">{d.png_count}</span>
                    <span className="km-mt-st">
                      <span className={'km-badge ' + (d.training_status === 'Trained' ? 'ok' : 'todo')}>
                        {d.training_status === 'Trained' ? 'เทรนแล้ว' : 'รอเทรน'}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            {progress && (
              <div className="km-prog">
                <div className="km-prog-lbl">
                  กำลังเทรน {docs.find(d => d.km_id === progress.km_id)?.source_file || progress.km_id} — หน้า {progress.i}/{progress.n}
                </div>
                <div className={'km-bar' + (progress.n > 0 ? '' : ' indet')}>
                  <div className="km-bar-fill"
                       style={{ width: progress.n > 0 ? Math.round(progress.i / progress.n * 100) + '%' : '100%' }} />
                </div>
              </div>
            )}
            <div className="km-modal-foot">
              <button type="button" className="btn-back" onClick={() => setShowTrain(false)} disabled={busy}>
                ยกเลิก
              </button>
              <button type="button" className="btn-save" onClick={doTrain}
                      disabled={busy || !Object.values(picked).some(Boolean)}>
                {busy ? '⏳ กำลังเทรน…' : `🚀 Train ที่เลือก (${Object.values(picked).filter(Boolean).length})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
