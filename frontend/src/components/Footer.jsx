import React from 'react'
import { Logo } from './Icons.jsx'

const COLS = [
  { title: 'เมนู', links: [
    { label: 'หน้าแรก', href: '#/' },
    { label: 'ป้อนเคส', href: '#/case' },
    { label: 'ค้นเคส', href: '#/search' },
    { label: 'Dashboard', href: '#/dashboard' },
  ]},
  { title: 'เทคโนโลยี', tech: [
    { k: 'LLM', v: 'Azure GPT-5.4-mini / Typhoon2 8B' },
    { k: 'ค้นหา', v: 'bge-m3 + cross-encoder rerank' },
    { k: 'ถอดเสียง (STT)', v: 'gpt-4o-transcribe / faster-whisper' },
    { k: 'อ่านออกเสียง (TTS)', v: 'gpt-4o-mini-tts' },
    { k: 'Backend', v: 'FastAPI' },
    { k: 'Frontend', v: 'React 18 + Vite 5' },
    { k: 'คลัง', v: 'Obsidian vault (.md)' },
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
            {c.tech ? (
              <nav>
                {c.tech.map((t) => (
                  <div className="tech-item" key={t.k}>
                    <span className="tech-k">{t.k}</span>
                    <span className="tech-v">{t.v}</span>
                  </div>
                ))}
              </nav>
            ) : (
              <nav>{c.links.map((l) => <a href={l.href} key={l.label}>{l.label}</a>)}</nav>
            )}
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
