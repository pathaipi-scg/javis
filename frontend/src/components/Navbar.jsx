import React from 'react'
import { Logo } from './Icons.jsx'

export default function Navbar() {
  return (
    <nav className="nav">
      <a href="#" className="brand">
        <span className="brand-mark"><Logo /></span>
        <span className="brand-name">Jarvis</span>
      </a>
      <div className="nav-links">
        <a href="#">ผู้ช่วย AI <span className="badge">NEW</span></a>
        <a href="#features">ความสามารถ</a>
        <a href="#">วิธีใช้งาน</a>
        <a href="#">ราคา</a>
        <a href="#">บล็อก</a>
      </div>
      <div className="nav-actions">
        <a href="#" className="btn-ghost">เข้าสู่ระบบ</a>
        <a href="#ask" className="btn-grad">ทดลองใช้ฟรี</a>
      </div>
    </nav>
  )
}
