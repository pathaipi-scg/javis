import React from 'react'
import { Logo } from './Icons.jsx'

export default function Navbar() {
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
        <a href="#/stt">ทดสอบ STT</a>
        <a href="#/dashboard">Dashboard</a>
      </div>
      <div className="nav-actions">
        <a href="#/ask" className="btn-grad">เริ่มใช้งาน</a>
      </div>
    </nav>
  )
}
