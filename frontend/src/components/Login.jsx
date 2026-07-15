import React, { useState } from 'react'
import { login } from '../auth.js'

// หน้า login — ขึ้นก่อนทุกหน้าเมื่อยังไม่มี token ที่ใช้ได้
// บัญชีมาจาก .env ฝั่ง backend (ADMIN_USERNAME / ADMIN_PASSWORD)
export default function Login({ onSuccess }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await login(username, password)
      onSuccess()
    } catch (e2) {
      setErr(e2.message)      // ข้อความกลางๆ จาก backend ไม่บอกว่า user หรือรหัสผิด
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <div className="streaks">
        <div className="streak-glow" /><div className="streak-line" /><div className="streak-glow2" />
      </div>
      <div className="login-wrap" style={{ position: 'relative', zIndex: 10, width: 'min(400px, 90vw)' }}>
        {/* ไฟ neon ฟุ้งหลังกล่อง — ต้องมาก่อน <form> ใน DOM กล่องถึงจะทับได้ */}
        <div className="login-glow" />
        <form
          onSubmit={submit}
          className="login-card"
          style={{
            position: 'relative', width: '100%',
            padding: '38px 34px', borderRadius: 18,
            // พื้นทึบพอให้อ่านออก — ของเดิมโปร่ง .03 ไฟ neon หลังกล่องจะทะลุมาบังตัวหนังสือ
            background: 'rgba(17,19,32,.82)', border: '1px solid rgba(255,255,255,.08)',
            backdropFilter: 'blur(10px)', boxShadow: '0 20px 60px rgba(0,0,0,.5)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 26 }}>
            <div className="brand-mark">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4">
                <path d="M12 2v6M12 16v6M2 12h6M16 12h6" strokeLinecap="round" />
                <circle cx="12" cy="12" r="3.4" />
              </svg>
            </div>
            <div>
              <div className="brand-name" style={{ fontSize: 19 }}>JARVIS</div>
              <div style={{ fontSize: 12.5, color: '#8b93ad' }}>เข้าสู่ระบบเพื่อใช้งาน</div>
            </div>
          </div>

          <label style={{ display: 'block', fontSize: 13, color: '#aab3cf', marginBottom: 6 }}>ชื่อผู้ใช้</label>
          <input
            value={username} onChange={e => setUsername(e.target.value)}
            autoFocus autoComplete="username" style={inputStyle}
          />

          <label style={{ display: 'block', fontSize: 13, color: '#aab3cf', margin: '16px 0 6px' }}>รหัสผ่าน</label>
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            autoComplete="current-password" style={inputStyle}
          />

          {err && (
            <div style={{
              marginTop: 16, padding: '10px 12px', borderRadius: 9, fontSize: 13.5,
              background: 'rgba(255,70,90,.1)', border: '1px solid rgba(255,70,90,.3)', color: '#ff9aa8',
            }}>{err}</div>
          )}

          <button
            type="submit" disabled={busy || !username || !password}
            style={{
              marginTop: 24, width: '100%', padding: '12px 20px', borderRadius: 11, border: 'none',
              fontFamily: "'Anuphan', sans-serif", fontSize: 15, fontWeight: 600, color: '#fff',
              cursor: busy ? 'default' : 'pointer',
              opacity: (busy || !username || !password) ? .5 : 1,
              background: 'linear-gradient(135deg,#4b7bff,#8b5cf6)',
              boxShadow: '0 8px 26px rgba(96,90,255,.45)',
            }}
          >{busy ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ'}</button>
        </form>
      </div>
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '11px 13px', borderRadius: 10,
  background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.13)',
  color: '#fff', fontFamily: "'Anuphan', sans-serif", fontSize: 15, outline: 'none',
}
