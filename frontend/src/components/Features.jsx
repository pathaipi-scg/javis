import React from 'react'
import { IcChat, IcGlobe, IcBook, IcBolt, IcLang, IcShield } from './Icons.jsx'

const FEATURES = [
  { icon: <IcChat />,   grad: 'linear-gradient(135deg,rgba(75,110,255,.9),rgba(139,92,246,.9))', halo: 'rgba(75,110,255,.22)', title: 'ถาม–ตอบจากเคสจริง (RAG)', body: 'ค้นเคสซ่อมบำรุงที่เคยเกิดจริงด้วยความหมาย แล้วสรุปคำตอบพร้อมแนบเลขเคสอ้างอิง — ไม่มโนเอง ตอบจากข้อมูลที่มีเท่านั้น' },
  { icon: <IcGlobe />,  grad: 'linear-gradient(135deg,rgba(139,92,246,.9),rgba(192,132,252,.9))', halo: 'rgba(150,80,240,.22)', title: 'พูดถาม–ฟังคำตอบ', body: 'กดไมค์แล้วพูดคำถาม ระบบถอดเสียงไทยด้วย Whisper และอ่านคำตอบกลับเป็นเสียง JARVIS ให้ฟังได้ทันที' },
  { icon: <IcBook />,   grad: 'linear-gradient(135deg,rgba(75,110,255,.9),rgba(52,211,153,.85))', halo: 'rgba(52,211,153,.18)', title: 'ป้อนเคสง่าย ครบถ้วน', body: 'กรอกฟอร์ม แนบไฟล์เสียงเล่าอาการ (ถอดให้อัตโนมัติ) แนบรูป แล้วตรวจพรีวิวไฟล์ก่อนบันทึกเข้าคลังความรู้' },
  { icon: <IcBolt />,   grad: 'linear-gradient(135deg,rgba(139,92,246,.9),rgba(75,110,255,.9))', halo: 'rgba(75,110,255,.22)', title: 'ค้นหาด้วยความหมาย', body: 'พิมพ์อาการที่เจอ ระบบหาเคสใกล้เคียงให้แม้ใช้คำไม่ตรงกัน พร้อมคะแนนความเกี่ยวข้องและแท็กหมวดปัญหา' },
  { icon: <IcLang />,   grad: 'linear-gradient(135deg,rgba(192,132,252,.9),rgba(75,110,255,.9))', halo: 'rgba(150,80,240,.22)', title: 'แยกข้อมูลตามโรงงาน/ฝ่าย', body: 'เลือกขอบเขตได้ว่าให้ตอบจากเคสโรงงานไหน ข้อมูลไม่ปนข้ามโรงงาน พร้อม Dashboard สรุปเคสและ downtime' },
  { icon: <IcShield />, grad: 'linear-gradient(135deg,rgba(52,211,153,.85),rgba(75,110,255,.9))', halo: 'rgba(52,211,153,.18)', title: 'ข้อมูลอยู่ในองค์กร', body: 'AI (Typhoon2) รันในเครื่องขององค์กรเอง ความรู้เก็บเป็นไฟล์ Markdown ใน Obsidian vault — อ่านได้ แก้ได้ ไม่ผูกกับใคร' },
]

export default function Features() {
  return (
    <section className="features" id="features">
      <div className="sec-head">
        <div className="eyebrow">Capabilities</div>
        <h2>JARVIS <span className="grad-text">ทำอะไรได้บ้าง</span></h2>
        <p className="sec-sub">คลังความรู้ซ่อมบำรุงที่ถามได้ด้วยเสียง ตอบจากเคสจริง และเก็บข้อมูลไว้ในองค์กรของคุณเอง</p>
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
