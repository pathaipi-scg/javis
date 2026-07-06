import React, { useState } from 'react'

// หน้าแรกแบบ JARVIS HUD — วงแหวนหมุน + สถานะ + ปุ่มโหมด (port จาก example_page/Jarvis HUD)
// โหมดเป็นแค่เดโมธีมสี ปุ่ม CTA ด้านล่างพาไปหน้าใช้งานจริง

const THEMES = {
  listening: { ring: '#35e0ea', accent: '#f5a623', label: '#46e08a', status: 'LISTENING', sub: 'พูดว่า "Jarvis…"', c: '#35e0ea' },
  speaking:  { ring: '#3fe9a0', accent: '#f5a623', label: '#3fe9a0', status: 'SPEAKING',  sub: 'กำลังตอบ…',      c: '#3fe9a0' },
  thinking:  { ring: '#7aa6dd', accent: '#f5a623', label: '#f5a623', status: 'THINKING',  sub: 'กำลังคิด…',      c: '#f5a623' },
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

// สร้างเส้นขีดรอบวง (ticks) — C คือจุดศูนย์กลาง viewBox 400x400
function ticks(count, r, len, color, w, o, accents, accentColor) {
  const C = 200, out = []
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2
    const c = Math.cos(a), s = Math.sin(a)
    const isA = accents.includes(i)
    out.push({
      key: i,
      x1: +(C + r * c).toFixed(2), y1: +(C + r * s).toFixed(2),
      x2: +(C + (r + len) * c).toFixed(2), y2: +(C + (r + len) * s).toFixed(2),
      color: isA ? accentColor : color, w: isA ? w + 0.8 : w, o: isA ? 1 : o,
    })
  }
  return out
}

export default function Landing() {
  const [mode, setMode] = useState('listening')
  const t = THEMES[mode]
  const bigTicks = ticks(56, 172, 15, t.ring, 3, 0.9, [4, 5, 17, 33], t.accent)
  const medTicks = ticks(90, 138, 7, t.ring, 1.5, 0.5, [22, 23, 61], t.accent)

  return (
    <section className="hud-landing">
      <div className="hud-glow" style={{ background: `radial-gradient(60% 45% at 50% 38%, ${hexA(t.ring, 0.07)}, transparent 70%)` }} />

      <div className="hud-ring-wrap">
        <svg viewBox="0 0 400 400" style={{ display: 'block', width: '100%', height: '100%', filter: `drop-shadow(0 0 6px ${hexA(t.ring, 0.25)})` }}>
          <defs>
            <radialGradient id="hud-core" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={t.ring} stopOpacity="0.32" />
              <stop offset="55%" stopColor={t.ring} stopOpacity="0.07" />
              <stop offset="100%" stopColor={t.ring} stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle cx="200" cy="200" r="92" fill="url(#hud-core)" className="hud-core" />

          <g className="hud-rot" style={{ animation: 'jv-spin 44s linear infinite' }}>
            <circle cx="200" cy="200" r="186" fill="none" stroke={t.ring} strokeWidth="4" strokeLinecap="round"
              strokeDasharray="150 34 96 40 70 26 118 34 82 50" opacity="0.9" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 60s linear infinite' }}>
            {bigTicks.map(k => (
              <line key={k.key} x1={k.x1} y1={k.y1} x2={k.x2} y2={k.y2}
                stroke={k.color} strokeWidth={k.w} strokeLinecap="round" opacity={k.o} />
            ))}
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin 30s linear infinite' }}>
            <circle cx="200" cy="200" r="160" fill="none" stroke={t.ring} strokeWidth="1.5"
              strokeDasharray="60 22 40 30 90 18" opacity="0.55" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin 22s linear infinite' }}>
            <circle cx="200" cy="200" r="150" fill="none" stroke={t.accent} strokeWidth="6" strokeLinecap="round"
              strokeDasharray="150 793" strokeDashoffset="-470" style={{ filter: 'drop-shadow(0 0 5px rgba(245,166,35,.6))' }} />
            <circle cx="200" cy="200" r="150" fill="none" stroke={t.accent} strokeWidth="6" strokeLinecap="round"
              strokeDasharray="24 918" strokeDashoffset="-250" opacity="0.9" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 40s linear infinite' }}>
            {medTicks.map(k => (
              <line key={k.key} x1={k.x1} y1={k.y1} x2={k.x2} y2={k.y2}
                stroke={k.color} strokeWidth={k.w} strokeLinecap="round" opacity={k.o} />
            ))}
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin 52s linear infinite' }}>
            <circle cx="200" cy="200" r="120" fill="none" stroke={t.ring} strokeWidth="2" strokeDasharray="2 9" opacity="0.7" />
          </g>

          <g className="hud-rot" style={{ animation: 'jv-spin-rev 34s linear infinite' }}>
            <circle cx="200" cy="200" r="104" fill="none" stroke={t.ring} strokeWidth="1.5" strokeDasharray="1.2 7" opacity="0.5" />
          </g>

          <circle cx="200" cy="200" r="86" fill="none" stroke={t.ring} strokeWidth="1" opacity="0.35" />
        </svg>

        <div className="hud-title" style={{ textShadow: `0 0 12px ${hexA(t.ring, 0.55)}, 0 0 2px rgba(255,255,255,.7)` }}>
          J.A.R.V.I.S.
        </div>
      </div>

      <div className="hud-status">
        <span className="hud-dot" style={{ background: t.label, color: t.label }} />
        <span className="hud-status-text" style={{ color: t.label, textShadow: `0 0 10px ${hexA(t.label, 0.5)}` }}>{t.status}</span>
      </div>
      <div className="hud-sub"><span className="hud-sub-dot" />{t.sub}</div>

      <div className="hud-modes">
        {Object.keys(THEMES).map(key => {
          const active = key === mode
          const col = THEMES[key].c
          return (
            <button key={key} onClick={() => setMode(key)} className="hud-mode-btn"
              style={{
                color: active ? '#04060a' : col,
                background: active ? col : hexA(col, 0.08),
                borderColor: active ? col : hexA(col, 0.4),
                boxShadow: active ? `0 0 16px -2px ${hexA(col, 0.7)}` : 'none',
              }}>
              {key.toUpperCase()}
            </button>
          )
        })}
      </div>

      <div className="hud-ctas">
        <a href="#/ask" className="hud-cta hud-cta-main">ถาม JARVIS →</a>
        <a href="#/graph" className="hud-cta">Knowledge Graph</a>
        <a href="#/case" className="hud-cta">ป้อนเคส</a>
      </div>
    </section>
  )
}
