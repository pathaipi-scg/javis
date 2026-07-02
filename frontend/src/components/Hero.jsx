import React from 'react'
import { Building, User, Check, Arrow } from './Icons.jsx'
import AiOrb from './AiOrb.jsx'

const SUBS = {
  biz: 'Automate support & workflows — ผู้ช่วย AI สำหรับทีมและองค์กร ตอบลูกค้าและทำงานแทนคุณทุกช่องทาง',
  ind: 'Your personal AI companion — ผู้ช่วยส่วนตัวที่ช่วยคิด ช่วยเขียน ค้นหาคำตอบ และจัดการงานในทุกวัน',
}

export default function Hero({ audience, setAudience }) {
  return (
    <header className="hero">
      <div className="toggle">
        <button
          className={audience === 'biz' ? 'active' : 'idle'}
          onClick={() => setAudience('biz')}
        >
          <Building /> สำหรับธุรกิจ
        </button>
        <button
          className={audience === 'ind' ? 'active' : 'idle'}
          onClick={() => setAudience('ind')}
        >
          <User /> สำหรับบุคคลทั่วไป
        </button>
      </div>

      <h1>
        ผู้ช่วย AI ที่ <span className="grad-text">ถามได้ ตอบได้</span><br />
        ทุกเรื่อง ทุกเวลา
      </h1>

      <p className="hero-sub" key={audience}>{SUBS[audience]}</p>

      <div className="checks">
        <span className="check"><Check /> ทดลองฟรี 14 วัน</span>
        <span className="check"><Check /> ตอบได้กว่า 50 ภาษา</span>
        <span className="check"><Check /> เชื่อมต่อ 10+ ช่องทาง</span>
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
