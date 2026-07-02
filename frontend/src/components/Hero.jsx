import React from 'react'
import { Check, Arrow } from './Icons.jsx'
import AiOrb from './AiOrb.jsx'

export default function Hero() {
  return (
    <header className="hero">
      <h1>
        ผู้ช่วยซ่อมบำรุงที่ <span className="grad-text">ถามได้ ตอบได้</span><br />
        จากเคสจริงของโรงงาน
      </h1>

      <p className="hero-sub">
        พิมพ์หรือพูดถาม — JARVIS ค้นเคสซ่อมบำรุงที่เคยเกิดขึ้นจริง
        แล้วสรุปคำตอบพร้อมอ้างอิงเคส ด้วย AI ที่รันอยู่ในองค์กรของคุณเอง
      </p>

      <div className="checks">
        <span className="check"><Check /> ตอบพร้อมอ้างอิงเคสจริง (case id)</span>
        <span className="check"><Check /> พูดถาม–ฟังคำตอบเป็นเสียงได้</span>
        <span className="check"><Check /> ข้อมูลอยู่ในองค์กร ไม่ออกไปไหน</span>
      </div>

      <div className="cta-wrap">
        <a href="#/ask" className="cta">
          <span className="label">เริ่มใช้ JARVIS — ถามจากเคสซ่อมบำรุงจริง</span>
          <span className="arrow"><Arrow /></span>
        </a>
      </div>

      <AiOrb />
    </header>
  )
}
