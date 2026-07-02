import React from 'react'
import { Logo } from './Icons.jsx'

const COLS = [
  { title: 'เมนู', links: [
    { label: 'ถาม JARVIS', href: '#/ask' },
    { label: 'ป้อนเคส', href: '#/case' },
    { label: 'ค้นเคส', href: '#/search' },
    { label: 'Dashboard', href: '#/dashboard' },
  ]},
  { title: 'หน้าเดิม (Legacy)', links: [
    { label: 'ป้อนข้อมูล (ฟอร์มเดิม)', href: '/legacy' },
    { label: 'ทดสอบ STT', href: '/stt' },
    { label: 'ถาม (หน้าเดิม)', href: '/ask' },
  ]},
  { title: 'เทคโนโลยี', links: [
    { label: 'LLM: Typhoon2 8B (local)', href: '#' },
    { label: 'ค้นหา: bge-m3 embeddings', href: '#' },
    { label: 'ถอดเสียง: faster-whisper', href: '#' },
    { label: 'คลัง: Obsidian vault (.md)', href: '#' },
  ]},
]

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-top">
        <div>
          <a href="#/" className="brand">
            <span className="brand-mark" style={{ width: 32, height: 32 }}><Logo size={15} /></span>
            <span className="brand-name" style={{ fontSize: 19 }}>Jarvis</span>
          </a>
          <p>คลังความรู้ซ่อมบำรุงเครื่องจักร — บันทึกเคส ค้นหา และถาม-ตอบจากเคสจริง ด้วย AI ในองค์กร</p>
        </div>
        {COLS.map((c) => (
          <div className="footer-col" key={c.title}>
            <h4>{c.title}</h4>
            <nav>{c.links.map((l) => <a href={l.href} key={l.label}>{l.label}</a>)}</nav>
          </div>
        ))}
      </div>
      <div className="footer-bottom">
        <span>© 2026 JARVIS — Maintenance Knowledge Base</span>
        <span>ถามได้ ตอบได้ จากเคสจริง</span>
      </div>
    </footer>
  )
}
