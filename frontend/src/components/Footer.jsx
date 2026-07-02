import React from 'react'
import { Logo } from './Icons.jsx'

const COLS = [
  { title: 'ผลิตภัณฑ์', links: ['ผู้ช่วย AI', 'แชตบอต', 'ฐานความรู้', 'API'] },
  { title: 'บริษัท', links: ['เกี่ยวกับเรา', 'บล็อก', 'ร่วมงานกับเรา', 'ติดต่อ'] },
  { title: 'ช่วยเหลือ', links: ['ศูนย์ช่วยเหลือ', 'สถานะระบบ', 'ความเป็นส่วนตัว', 'เงื่อนไขการใช้งาน'] },
]

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-top">
        <div>
          <a href="#" className="brand">
            <span className="brand-mark" style={{ width: 32, height: 32 }}><Logo size={15} /></span>
            <span className="brand-name" style={{ fontSize: 19 }}>Jarvis</span>
          </a>
          <p>ผู้ช่วย AI ที่ถามได้ ตอบได้ ทุกเรื่อง ทุกเวลา — ยกระดับการทำงานและบริการลูกค้าของคุณ</p>
        </div>
        {COLS.map((c) => (
          <div className="footer-col" key={c.title}>
            <h4>{c.title}</h4>
            <nav>{c.links.map((l) => <a href="#" key={l}>{l}</a>)}</nav>
          </div>
        ))}
      </div>
      <div className="footer-bottom">
        <span>© 2026 Jarvis AI. สงวนลิขสิทธิ์ทุกประการ</span>
        <span>Made with AI · ถามได้ ตอบได้</span>
      </div>
    </footer>
  )
}
