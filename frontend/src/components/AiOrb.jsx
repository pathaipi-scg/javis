import React from 'react'
import { Logo, Spark } from './Icons.jsx'

// Purely decorative AI core: glowing gradient orb, spinning rings,
// orbiting dots and floating chat chips. All CSS-driven.
export default function AiOrb() {
  return (
    <div className="orb-stage" aria-hidden="true">
      <div className="orb">
        <div className="orb-glow" />
        <div className="orb-ring" />
        <div className="orb-dashed" />
        <div className="orb-core"><Logo size={58} /></div>
        <div className="orb-dot-a"><span /></div>
        <div className="orb-dot-b"><span /></div>
      </div>

      <div className="chip chip-a">
        <div className="chip-q"><span className="d" />"forming press แรงดันตก แก้ยังไง"</div>
      </div>
      <div className="chip chip-b">
        <div className="chip-r"><Spark />"เปลี่ยนชุดซีลแล้วไล่ลม 📎 MTN-2026-0001"</div>
      </div>
      <div className="chip chip-c">
        <div className="chip-typing">
          <span className="dots"><span /><span /><span /></span>
          Jarvis กำลังคิด…
        </div>
      </div>
    </div>
  )
}
