import React from 'react'
import { IcChat, IcGlobe, IcBook, IcBolt, IcLang, IcShield } from './Icons.jsx'

const FEATURES = [
  { icon: <IcChat />,   grad: 'linear-gradient(135deg,rgba(75,110,255,.9),rgba(139,92,246,.9))', halo: 'rgba(75,110,255,.22)', title: 'ถาม–ตอบอัจฉริยะ', body: 'เข้าใจภาษาธรรมชาติ ตอบตรงประเด็น เข้าใจบริบทการสนทนาต่อเนื่องเหมือนคุยกับคนจริง' },
  { icon: <IcGlobe />,  grad: 'linear-gradient(135deg,rgba(139,92,246,.9),rgba(192,132,252,.9))', halo: 'rgba(150,80,240,.22)', title: 'เชื่อมต่อทุกช่องทาง', body: 'รวมทุกแชตไว้ที่เดียว — Messenger, LINE, อีเมล, เว็บไซต์ และช่องทางอื่นกว่า 10 แพลตฟอร์ม' },
  { icon: <IcBook />,   grad: 'linear-gradient(135deg,rgba(75,110,255,.9),rgba(52,211,153,.85))', halo: 'rgba(52,211,153,.18)', title: 'เรียนรู้จากข้อมูลคุณ', body: 'อัปโหลดเอกสาร คู่มือ หรือฐานความรู้ ให้ Jarvis ตอบจากข้อมูลจริงขององค์กรคุณอย่างแม่นยำ' },
  { icon: <IcBolt />,   grad: 'linear-gradient(135deg,rgba(139,92,246,.9),rgba(75,110,255,.9))', halo: 'rgba(75,110,255,.22)', title: 'ทำงานอัตโนมัติ', body: 'ตั้งค่าให้ Jarvis จัดการงานซ้ำ ๆ ส่งต่องาน แจ้งเตือน และตอบลูกค้าได้เองตลอด 24 ชั่วโมง' },
  { icon: <IcLang />,   grad: 'linear-gradient(135deg,rgba(192,132,252,.9),rgba(75,110,255,.9))', halo: 'rgba(150,80,240,.22)', title: 'รองรับหลายภาษา', body: 'สนทนาได้ทั้งไทย อังกฤษ และอีกกว่า 50 ภาษา สลับภาษากลางบทสนทนาได้อย่างเป็นธรรมชาติ' },
  { icon: <IcShield />, grad: 'linear-gradient(135deg,rgba(52,211,153,.85),rgba(75,110,255,.9))', halo: 'rgba(52,211,153,.18)', title: 'ปลอดภัยระดับองค์กร', body: 'เข้ารหัสข้อมูลทุกชั้น รองรับมาตรฐานความเป็นส่วนตัว ข้อมูลของคุณเป็นความลับเสมอ' },
]

export default function Features() {
  return (
    <section className="features" id="features">
      <div className="sec-head">
        <div className="eyebrow">Capabilities</div>
        <h2>Jarvis <span className="grad-text">ทำอะไรได้บ้าง</span></h2>
        <p className="sec-sub">ผู้ช่วยอัจฉริยะที่พร้อมตอบทุกคำถาม เชื่อมต่อทุกช่องทาง และทำงานแทนคุณ 24 ชั่วโมง</p>
      </div>
      <div className="feature-grid">
        {FEATURES.map((f) => (
          <div className="card" key={f.title}>
            <div className="halo" style={{ background: `radial-gradient(circle, ${f.halo}, transparent 70%)` }} />
            <div className="icon" style={{ background: f.grad, boxShadow: '0 8px 22px rgba(96,90,255,.4)' }}>{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
