// คำปลุก "hey jarvis" ใช้ openWakeWord (voice/oww.js) — จับจาก pattern เสียงโดยตรง
// ไม่ผ่าน text แล้ว จึงไม่มี WAKE_RE ที่นี่

// ── ตัวจับคำสั่งนำทางด้วยเสียง (ใช้ร่วมกันทั้ง Landing + VoiceNav) ──────────
// STT ไทยถอด "dashboard/graph" เพี้ยนได้หลายแบบ เลยครอบสะกดกว้างๆ ไว้
// กติกา:
//   - ถ้ามีคำสั่งนำ (เปิด/ไป/open…) + ชื่อหน้า -> เป็นคำสั่งนำทางแน่นอน
//   - ถ้าไม่มีคำสั่งนำ แต่พูดสั้นๆ (คำเดียว/วลีสั้น) แล้วตรงชื่อหน้า -> ถือเป็นคำสั่งด้วย
//     (เช่น พูดแค่ "dashboard") — เพราะพูดหลัง wake word มักตั้งใจสั่งอยู่แล้ว
//   - ถ้าประโยคยาว + ไม่มีคำสั่งนำ -> ถือเป็น "คำถาม" (เช่น "เปิดฝาปั๊มยังไง" ไม่นับ)

export const NAV_VERB = /(เปิด|ไป(ที่|ยัง)?|กลับ|พา(ไป)?|ขอ(ไป|ดู)?|โชว์|แสดง|เข้า|ดู|เรียก|open|go(\s*(to|back))?|show|navigate|back(\s*to)?)/i

export const NAV_ROUTES = [
  { hash: '#/dashboard', label: 'แดชบอร์ด',  re: /(dashboard|dash\s?board|แด(?:ช|ส|ซ)\s?บอ|แดชบอด|แดช|หน้าฟอง|ฟองสบู่|บับเบิ้?ล|bubble)/i },
  { hash: '#/graph',     label: 'กราฟ',       re: /(graph|กร(?:า|๊า|าฟ)(?:ฟ|บ|ป|ฟความรู้)?|knowledge\s*graph|เส้นเชื่อม|แผนภาพความรู้)/i },
  { hash: '#/search',    label: 'ค้นเคส',     re: /(ค้น\s?(เคส|หา)?|หาเคส|search|เสิร์?ช|เสิด|เสิช)/i },
  { hash: '#/case',      label: 'ป้อนเคส',    re: /(ป้อนเคส|กรอกเคส|เพิ่มเคส|บันทึกเคส|ลงเคส|สร้างเคส|เคสใหม่|new\s*case|add\s*case)/i },
  { hash: '#/stt',       label: 'ทดสอบ STT',  re: /(ทดสอบ\s*(stt|เสียง)|ถอดเสียง|แปลงเสียง|\bstt\b|สปีช|speech\s*to\s*text)/i },
  { hash: '#/stats',     label: 'สรุป',       re: /(สรุป|สถิติ|รายงาน|stats|statistic|summary|report)/i },
  { hash: '#/',          label: 'หน้าแรก',    re: /(หน้าแรก|หน้าหลัก|หน้าโฮม|โฮม|กลับบ้าน|ถามจาร์?วิส|home\s*(page)?|main\s*(page|menu)?|เมนูหลัก|แลนดิ้ง|landing)/i },
]

// นับ "คำ" หยาบๆ (ไทยไม่เว้นวรรค เลยนับตามช่องว่าง + ความยาว)
function isShortCommand(s) {
  const words = s.split(/\s+/).filter(Boolean).length
  return words <= 4 && s.length <= 24
}

// คืน { hash, label } ถ้าเป็นคำสั่งนำทาง, ไม่งั้น null -> ถือเป็นคำถาม RAG
export function matchNav(text) {
  const s = (text || '').trim().toLowerCase()
  if (!s) return null
  const hasVerb = NAV_VERB.test(s)
  const short = isShortCommand(s)
  if (!hasVerb && !short) return null   // ประโยคยาว + ไม่มีคำสั่งนำ = คำถาม
  for (const r of NAV_ROUTES) if (r.re.test(s)) return r
  return null
}
