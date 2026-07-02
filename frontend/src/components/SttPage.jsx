import React, { useEffect, useRef, useState } from 'react'

// หน้าทดสอบ STT — อัปคลิปเสียง/วิดีโอ -> Whisper ถอด -> Typhoon ดึงข้อมูลเครื่องเป็นตาราง
// ไว้วัดความแม่นของ Whisper กับเสียงจริง (ไม่เกี่ยวกับการบันทึกเคส)

export default function SttPage() {
  const [cfg, setCfg] = useState(null)      // {model, device, remote}
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    fetch('/api/stt-config').then(r => r.json()).then(setCfg).catch(() => {})
  }, [])

  async function run(e) {
    e.preventDefault()
    if (!file || loading) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('audio', file)
      const res = await fetch('/api/stt', { method: 'POST', body: fd })
      if (!res.ok) throw new Error('bad status ' + res.status)
      setResult(await res.json())
    } catch (e) {
      setError('ถอดเสียงไม่ได้ — ตรวจว่ารัน backend ที่พอร์ต 5000 แล้ว')
    } finally {
      setLoading(false)
    }
  }

  function copyText() {
    if (result?.text) navigator.clipboard.writeText(result.text)
  }

  return (
    <section className="case-wrap">
      <div className="case-card">
        <div className="case-head">
          <h2>🎙️ ทดสอบ STT
            {result?.is_mock && <span className="mock-badge">MOCK — ยังต่อ Whisper ไม่ได้</span>}
          </h2>
          <span className="case-sub">เลือกไฟล์เสียง/วิดีโอ → ถอดเป็นข้อความ → ดูข้อมูลเครื่องที่ดึงได้ (วัดความแม่นกับเสียงจริง)</span>
        </div>

        {cfg && (
          <div className="stt-cfg">
            <span className="case-tag on">โมเดล: {cfg.model}</span>
            <span className="case-tag on">อุปกรณ์: {cfg.device}</span>
            <span className="case-tag on">ถอดที่: {cfg.remote ? 'server (remote)' : 'เครื่องนี้ (local)'}</span>
          </div>
        )}

        <form onSubmit={run}>
          <label>🎵 ไฟล์เสียง / วิดีโอ</label>
          <input ref={inputRef} className="case-file" type="file" accept="audio/*,video/*"
                 onChange={(e) => setFile(e.target.files[0] || null)} />
          <div className="case-actions">
            <button className="btn-save" type="submit" disabled={loading || !file}>
              {loading ? '⏳ กำลังถอดเสียง... (คลิปยาวใช้เวลาหลายนาที)' : 'แปลงเป็นข้อความ'}
            </button>
          </div>
        </form>

        {error && <div className="case-error">{error}</div>}
      </div>

      {result && (
        <>
          <div className="case-card">
            <div className="stt-meta">
              <span>📄 <b>{result.filename}</b></span>
              <span>· ⏱️ ถอดใน <b>{result.seconds}</b> วิ</span>
              <button type="button" className="hist-clear" style={{ marginLeft: 'auto' }} onClick={copyText}>คัดลอก</button>
            </div>
            <label>📝 ข้อความที่ถอดได้</label>
            <div className="stt-transcript">{result.text}</div>
          </div>

          <div className="case-card">
            <div className="case-head">
              <h2 style={{ fontSize: 18 }}>🤖 ผลสรุปจาก Typhoon
                {result.llm_mock && <span className="mock-badge">MOCK — ต่อ Typhoon ไม่ติด</span>}
              </h2>
              <span className="case-sub">⏱️ สรุปใน {result.llm_seconds} วิ</span>
            </div>
            <label>สรุปภาพรวม</label>
            <div className="stt-summary">{result.summary || '— (ไม่มีสรุป)'}</div>

            <label>เครื่องจักรที่ดึงได้ ({result.machines.length})</label>
            {result.machines.length > 0 ? (
              <table className="stt-table">
                <thead>
                  <tr><th>เครื่อง</th><th>อาการ</th><th>จุด/ตำแหน่ง</th><th>วันที่ซ่อม</th><th>การแก้ไข</th></tr>
                </thead>
                <tbody>
                  {result.machines.map((m, i) => (
                    <tr key={i}>
                      <td>{m.machine || '-'}</td>
                      <td>{m.issue || '-'}</td>
                      <td>{m.location || '-'}</td>
                      <td>{m.repair_date || '-'}</td>
                      <td>{m.action || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="hist-empty">— Typhoon ดึงเครื่องจักรไม่ได้ (ข้อความอาจไม่มีข้อมูลเครื่อง หรือ transcript เพี้ยนเกินไป)</div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
