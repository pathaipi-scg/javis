import React from 'react'
import { Logo } from './Icons.jsx'

export default function Navbar({ models = { local: [], api: [] }, model = '', setModel }) {
  return (
    <nav className="nav">
      <a href="#/" className="brand">
        <span className="brand-mark"><Logo /></span>
        <span className="brand-name">Jarvis</span>
      </a>
      <div className="nav-links">
        <a href="#/">หน้าแรก</a>
        <a href="#/ask">ถาม JARVIS <span className="badge">RAG</span></a>
        <a href="#/case">ป้อนเคส</a>
        <a href="#/search">ค้นเคส</a>
        <a href="#/graph">Graph</a>
        <a href="#/stt">ทดสอบ STT</a>
        <a href="#/dashboard">Dashboard</a>
        <a href="#/stats">สรุป</a>
      </div>
      <div className="nav-actions">
        {setModel && (
          <label className="nav-model" title="เลือกโมเดลที่ใช้ตอบ">
            <span className="nav-model-label">โมเดล</span>
            <select value={model} onChange={e => setModel(e.target.value)}>
              {models.local.length > 0 && (
                <optgroup label="Local (ในเครื่อง)">
                  {models.local.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                </optgroup>
              )}
              <optgroup label="API (คลาวด์)">
                {models.api.length > 0
                  ? models.api.map(m => <option key={m.id} value={m.id}>{m.label}</option>)
                  : <option disabled>— เพิ่มภายหลัง —</option>}
              </optgroup>
            </select>
          </label>
        )}
        <a href="#/ask" className="btn-grad">เริ่มใช้งาน</a>
      </div>
    </nav>
  )
}
