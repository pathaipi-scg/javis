import React, { useEffect, useState } from 'react'

// หน้าป้อนเคสซ่อมบำรุง (tag-first) — ฟอร์ม -> พรีวิว .md (แก้ได้) -> ยืนยันบันทึกลง vault
// สมองอยู่ backend ทั้งหมด: /api/form-options, /api/cases/preview, /api/cases/save

const EMPTY = {
  machine: '', plant: '', department: '', line: '', component: '',
  severity: 'medium', status: 'resolved', downtime_min: '', parts_used: '',
  source: 'morning_meeting', symptom: '', cause: '', solution: '', result: '', caption: '',
}

export default function CasePage() {
  const [opts, setOpts] = useState({ tags: [], plants: [], departments: [], severities: [], statuses: [], sources: [] })
  const [f, setF] = useState({ ...EMPTY })
  const [tags, setTags] = useState([])        // tag ที่เลือก (chip)
  const [tagInput, setTagInput] = useState('')
  const [plantNew, setPlantNew] = useState('')
  const [deptNew, setDeptNew] = useState('')
  const [audio, setAudio] = useState(null)    // File เสียง (ถอดต่อท้ายอาการ)
  const [image, setImage] = useState(null)    // File รูปแนบ
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // พรีวิว: {case_id, md, image_name, image_path}
  const [preview, setPreview] = useState(null)
  const [md, setMd] = useState('')
  const [saved, setSaved] = useState(null)    // {case_id, written}

  useEffect(() => {
    fetch('/api/form-options').then(r => r.json()).then(setOpts).catch(() => {})
  }, [])

  function set(k, v) { setF(prev => ({ ...prev, [k]: v })) }

  function toggleTag(t) {
    setTags(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t])
  }

  function addTagInput() {
    const t = tagInput.replace(/^#/, '').trim()
    if (t && !tags.includes(t)) setTags([...tags, t])
    setTagInput('')
  }

  async function doPreview(e) {
    e.preventDefault()
    if (loading) return
    setLoading(true)
    setError('')
    try {
      const fd = new FormData()
      const plant = f.plant === '__new__' ? plantNew.trim() : f.plant
      const department = f.department === '__new__' ? deptNew.trim() : f.department
      Object.entries({ ...f, plant, department, tags: tags.join(' ') })
        .forEach(([k, v]) => fd.append(k, v))
      if (audio) fd.append('audio', audio)
      if (image) fd.append('image', image)
      const res = await fetch('/api/cases/preview', { method: 'POST', body: fd })
      if (!res.ok) throw new Error('bad status ' + res.status)
      const data = await res.json()
      setPreview(data)
      setMd(data.md)
      // ถ้าถอดเสียงมา อัปเดตช่องอาการไว้ด้วย (เผื่อกดกลับไปแก้)
      if (data.symptom) set('symptom', data.symptom)
      setAudio(null)                       // เสียงถูกถอดแล้ว ไม่ต้องส่งซ้ำ
      window.scrollTo(0, 0)
    } catch (e) {
      setError('สร้างพรีวิวไม่ได้ — ตรวจว่ารัน backend (demo/app.py) ที่พอร์ต 5000 แล้ว')
    } finally {
      setLoading(false)
    }
  }

  async function doSave() {
    if (loading) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/cases/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ md, image_path: preview.image_path, image_name: preview.image_name }),
      })
      if (!res.ok) throw new Error('bad status ' + res.status)
      const data = await res.json()
      if (!data.ok) throw new Error('save failed')
      setSaved(data)
      setPreview(null)
      setF({ ...EMPTY })
      setTags([])
      setImage(null)
      window.scrollTo(0, 0)
    } catch (e) {
      setError('บันทึกไม่สำเร็จ — ตรวจ VAULT_PATH ใน .env และดู log backend')
    } finally {
      setLoading(false)
    }
  }

  // ── โหมดพรีวิว ──
  if (preview) {
    return (
      <section className="case-wrap">
        <div className="case-card">
          <div className="case-head">
            <h2>👁 พรีวิวเคส <span className="case-id">{preview.case_id}</span></h2>
            <span className="case-sub">ตรวจ/แก้เนื้อไฟล์ .md ได้ตรงนี้ — ยังไม่ถูกบันทึกจนกว่าจะกดยืนยัน</span>
          </div>
          {preview.image_name && <div className="case-note">🖼 รูปแนบ: {preview.image_name} (จะถูกก๊อปเข้า vault ตอนบันทึก)</div>}
          <textarea className="case-md" value={md} onChange={(e) => setMd(e.target.value)} spellCheck={false} />
          <div className="case-actions">
            <button type="button" className="btn-save" onClick={doSave} disabled={loading}>
              {loading ? 'กำลังบันทึก…' : '💾 ยืนยันบันทึกลง vault'}
            </button>
            <button type="button" className="btn-back" onClick={() => setPreview(null)} disabled={loading}>
              ← กลับไปแก้ฟอร์ม
            </button>
          </div>
          {error && <div className="case-error">{error}</div>}
        </div>
      </section>
    )
  }

  // ── โหมดฟอร์ม ──
  return (
    <section className="case-wrap">
      {saved && (
        <div className="case-saved">
          ✅ บันทึกเคส <b>{saved.case_id}</b> แล้ว — {saved.written}
          <button type="button" className="case-saved-x" onClick={() => setSaved(null)}>✕</button>
        </div>
      )}

      <form className="case-card" onSubmit={doPreview}>
        <div className="case-head">
          <h2>📥 ป้อนเคสซ่อมบำรุง</h2>
          <span className="case-sub">กรอกเคส → พรีวิว .md → ยืนยันบันทึกลง Obsidian vault (แนบเสียง/รูปได้)</span>
        </div>

        <div className="case-grid">
          <div>
            <label>เครื่องจักร *</label>
            <input className="case-input" required value={f.machine}
                   onChange={(e) => set('machine', e.target.value)} placeholder="เช่น Forming Press A" />
          </div>
          <div>
            <label>จุด/ชิ้นส่วน (component)</label>
            <input className="case-input" value={f.component}
                   onChange={(e) => set('component', e.target.value)} placeholder="เช่น Hydraulic valve V-203" />
          </div>

          <div>
            <label>โรงงาน *</label>
            <select className="case-input" required value={f.plant} onChange={(e) => set('plant', e.target.value)}>
              <option value="" disabled>— เลือกโรงงาน —</option>
              {opts.plants.map((p) => <option key={p} value={p}>{p}</option>)}
              <option value="__new__">➕ เพิ่มโรงงานใหม่…</option>
            </select>
            {f.plant === '__new__' &&
              <input className="case-input case-newfield" value={plantNew} required
                     onChange={(e) => setPlantNew(e.target.value)} placeholder="ชื่อโรงงานใหม่" />}
          </div>
          <div>
            <label>ฝ่าย *</label>
            <select className="case-input" required value={f.department} onChange={(e) => set('department', e.target.value)}>
              <option value="" disabled>— เลือกฝ่าย —</option>
              {opts.departments.map((d) => <option key={d} value={d}>{d}</option>)}
              <option value="__new__">➕ เพิ่มฝ่ายใหม่…</option>
            </select>
            {f.department === '__new__' &&
              <input className="case-input case-newfield" value={deptNew} required
                     onChange={(e) => setDeptNew(e.target.value)} placeholder="ชื่อฝ่ายใหม่" />}
          </div>

          <div>
            <label>ไลน์ผลิต</label>
            <input className="case-input" value={f.line}
                   onChange={(e) => set('line', e.target.value)} placeholder="เช่น Line 2" />
          </div>
          <div>
            <label>ที่มา (source)</label>
            <select className="case-input" value={f.source} onChange={(e) => set('source', e.target.value)}>
              {opts.sources.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div>
            <label>ความรุนแรง</label>
            <select className="case-input" value={f.severity} onChange={(e) => set('severity', e.target.value)}>
              {opts.severities.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label>สถานะ</label>
            <select className="case-input" value={f.status} onChange={(e) => set('status', e.target.value)}>
              {opts.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div>
            <label>เวลาหยุดเครื่อง (นาที)</label>
            <input className="case-input" type="number" min="0" value={f.downtime_min}
                   onChange={(e) => set('downtime_min', e.target.value)} placeholder="เช่น 45" />
          </div>
          <div>
            <label>อะไหล่ที่ใช้</label>
            <input className="case-input" value={f.parts_used}
                   onChange={(e) => set('parts_used', e.target.value)} placeholder="เช่น ชุดซีลวาล์ว 1 ชุด" />
          </div>
        </div>

        <label>แท็ก (คลิกเลือก หรือพิมพ์เพิ่ม)</label>
        <div className="case-tags">
          {[...new Set([...opts.tags, ...tags])].map((t) => (
            <button key={t} type="button"
                    className={'case-tag' + (tags.includes(t) ? ' on' : '')}
                    onClick={() => toggleTag(t)}>#{t}</button>
          ))}
        </div>
        <input className="case-input" value={tagInput}
               onChange={(e) => setTagInput(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTagInput() } }}
               placeholder="พิมพ์แท็กใหม่แล้วกด Enter (แท็กแรก = category)" />

        <label>อาการ (Symptom) *</label>
        <textarea className="case-input case-ta" required value={f.symptom}
                  onChange={(e) => set('symptom', e.target.value)}
                  placeholder="อาการที่พบ… (แนบไฟล์เสียงด้านล่างได้ — จะถอดข้อความต่อท้ายช่องนี้)" />

        <div className="case-grid">
          <div>
            <label>🎵 ไฟล์เสียงเล่าอาการ (ถอดด้วย Whisper)</label>
            <input className="case-file" type="file" accept="audio/*,video/*"
                   onChange={(e) => setAudio(e.target.files[0] || null)} />
          </div>
          <div>
            <label>🖼 รูปประกอบ (แนบใน .md)</label>
            <input className="case-file" type="file" accept="image/*"
                   onChange={(e) => setImage(e.target.files[0] || null)} />
          </div>
        </div>
        {image && (
          <>
            <label>คำอธิบายรูป (caption)</label>
            <input className="case-input" value={f.caption}
                   onChange={(e) => set('caption', e.target.value)} placeholder="รูปนี้คืออะไร" />
          </>
        )}

        <label>สาเหตุ (Root cause)</label>
        <textarea className="case-input case-ta" value={f.cause}
                  onChange={(e) => set('cause', e.target.value)} placeholder="สาเหตุที่วิเคราะห์ได้…" />

        <label>วิธีแก้ (Solution)</label>
        <textarea className="case-input case-ta" value={f.solution}
                  onChange={(e) => set('solution', e.target.value)} placeholder="ทำอะไรไปบ้าง…" />

        <label>ผลลัพธ์ (Result)</label>
        <textarea className="case-input case-ta" value={f.result}
                  onChange={(e) => set('result', e.target.value)} placeholder="ผลหลังแก้…" />

        <div className="case-actions">
          <button className="btn-save" type="submit" disabled={loading}>
            {loading ? (audio ? '⏳ กำลังถอดเสียง + สร้างพรีวิว…' : '⏳ กำลังสร้างพรีวิว…') : '👁 พรีวิวก่อนบันทึก'}
          </button>
        </div>
        {error && <div className="case-error">{error}</div>}
      </form>
    </section>
  )
}
