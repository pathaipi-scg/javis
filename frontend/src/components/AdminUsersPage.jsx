import React, { useEffect, useState } from 'react'
import { fetchUsers, registerUser } from '../auth.js'

// #/admin/users — จัดการผู้ใช้ (admin เท่านั้น)
// โชว์รายชื่อ user + ปุ่มเพิ่มผู้ใช้ (โมดัลตามฟอร์มต้นแบบ)
export default function AdminUsersPage() {
  const [users, setUsers] = useState([])
  const [err, setErr] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  async function reload() {
    try { setUsers(await fetchUsers()) }
    catch (e) { setErr(e.message) }       // ไม่ใช่ admin -> backend ตอบ 403 มาโชว์ตรงนี้
  }
  useEffect(() => { reload() }, [])

  return (
    <div className="container" style={{ maxWidth: 960, margin: '0 auto', padding: '28px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 24, margin: 0 }}>จัดการผู้ใช้</h1>
          <div style={{ color: '#8b93ad', fontSize: 13.5, marginTop: 4 }}>เฉพาะ admin เท่านั้นที่เพิ่มผู้ใช้ได้</div>
        </div>
        <button onClick={() => setShowAdd(true)} style={btnPrimary}>+ เพิ่มผู้ใช้</button>
      </div>

      {err && <div style={errBox}>{err}</div>}

      <div style={{ overflowX: 'auto', border: '1px solid rgba(255,255,255,.08)', borderRadius: 12 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: 'rgba(255,255,255,.04)', textAlign: 'left' }}>
              {['ID', 'Username', 'ชื่อ-สกุล', 'รหัสพนักงาน', 'อีเมล', 'Role', 'สถานะ'].map(h =>
                <th key={h} style={th}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{ borderTop: '1px solid rgba(255,255,255,.06)' }}>
                <td style={td}>{u.id}</td>
                <td style={td}>{u.username}</td>
                <td style={td}>{u.first_name} {u.last_name}</td>
                <td style={td}>{u.employee_id}</td>
                <td style={td}>{u.email}</td>
                <td style={td}><span style={roleBadge(u.role)}>{u.role}</span></td>
                <td style={td}>{u.is_active ? '✅ ใช้งาน' : '⛔ ปิด'}</td>
              </tr>
            ))}
            {users.length === 0 && !err && (
              <tr><td style={{ ...td, color: '#8b93ad' }} colSpan={7}>ยังไม่มีผู้ใช้</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <AddUserModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); reload() }}
        />
      )}
    </div>
  )
}

// โมดัลเพิ่มผู้ใช้ — ฟิลด์ตรงตามฟอร์มต้นแบบ
function AddUserModal({ onClose, onCreated }) {
  const [f, setF] = useState({
    first_name: '', last_name: '', username: '', password: '',
    employee_id: '', email: '', phone: '', role: 'user',
  })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setF({ ...f, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await registerUser(f)
      onCreated()
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <form onClick={e => e.stopPropagation()} onSubmit={submit} style={modal}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20 }}>เพิ่มผู้ใช้ใหม่</h2>
            <div style={{ color: '#8b93ad', fontSize: 13, marginTop: 4 }}>สร้างบัญชีผู้ใช้ใหม่ — เฉพาะ admin</div>
          </div>
          <button type="button" onClick={onClose} style={xBtn}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 18 }}>
          <Field label="ชื่อ (First Name)"><input style={inp} value={f.first_name} onChange={set('first_name')} autoFocus /></Field>
          <Field label="นามสกุล (Last Name)"><input style={inp} value={f.last_name} onChange={set('last_name')} /></Field>
        </div>
        <Field label="Username"><input style={inp} value={f.username} onChange={set('username')} autoComplete="off" /></Field>
        <Field label="Password"><input style={inp} type="password" value={f.password} onChange={set('password')} autoComplete="new-password" /></Field>
        <Field label="Employee ID"><input style={inp} value={f.employee_id} onChange={set('employee_id')} /></Field>
        <Field label="Email"><input style={inp} type="email" placeholder="user@jarvis.com" value={f.email} onChange={set('email')} /></Field>
        <Field label="เบอร์โทร (ไม่บังคับ)"><input style={inp} placeholder="090-xxx-xxxx" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Role">
          <select style={inp} value={f.role} onChange={set('role')}>
            <option value="user">User — ผู้ใช้ทั่วไป</option>
            <option value="approver">Approver — อนุมัติเคส</option>
            <option value="admin">Admin — ผู้ดูแลระบบ</option>
          </select>
        </Field>

        {err && <div style={errBox}>{err}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
          <button type="button" onClick={onClose} style={btnGhost}>ยกเลิก</button>
          <button type="submit" disabled={busy} style={{ ...btnPrimary, opacity: busy ? .5 : 1 }}>
            {busy ? 'กำลังเพิ่ม…' : 'เพิ่มผู้ใช้'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'block', marginTop: 14 }}>
      <span style={{ display: 'block', fontSize: 13, color: '#aab3cf', marginBottom: 6 }}>{label}</span>
      {children}
    </label>
  )
}

// ── styles ──
const inp = {
  width: '100%', padding: '11px 13px', borderRadius: 10, boxSizing: 'border-box',
  background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.13)',
  color: '#fff', fontFamily: "'Anuphan', sans-serif", fontSize: 14.5, outline: 'none',
}
const btnPrimary = {
  padding: '11px 20px', borderRadius: 11, border: 'none', color: '#fff',
  fontFamily: "'Anuphan', sans-serif", fontSize: 14.5, fontWeight: 600, cursor: 'pointer',
  // theme เดียวกับ navbar/login (ม่วง gradient) — ไม่ใช่ส้ม
  background: 'linear-gradient(135deg,#4b7bff,#8b5cf6)', boxShadow: '0 8px 26px rgba(96,90,255,.45)',
}
const btnGhost = {
  padding: '11px 20px', borderRadius: 11, cursor: 'pointer',
  background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.13)',
  color: '#cfd6ea', fontFamily: "'Anuphan', sans-serif", fontSize: 14.5,
}
const xBtn = {
  background: 'none', border: 'none', color: '#8b93ad', fontSize: 26, lineHeight: 1,
  cursor: 'pointer', padding: 0,
}
const overlay = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', backdropFilter: 'blur(3px)',
  display: 'grid', placeItems: 'center', zIndex: 100, padding: 16,
}
const modal = {
  width: 'min(440px, 96vw)', maxHeight: '92vh', overflowY: 'auto',
  background: 'rgba(20,22,36,.98)', border: '1px solid rgba(255,255,255,.1)',
  borderRadius: 16, padding: '24px 26px', boxShadow: '0 24px 70px rgba(0,0,0,.6)',
}
const errBox = {
  marginTop: 14, padding: '10px 12px', borderRadius: 9, fontSize: 13.5,
  background: 'rgba(255,70,90,.1)', border: '1px solid rgba(255,70,90,.3)', color: '#ff9aa8',
}
const th = { padding: '11px 14px', fontWeight: 600, color: '#aab3cf', fontSize: 13 }
const td = { padding: '10px 14px', color: '#e6e9f2' }
const roleBadge = (role) => ({
  padding: '3px 9px', borderRadius: 20, fontSize: 12.5, fontWeight: 600,
  background: role === 'admin' ? 'rgba(255,120,0,.18)' : role === 'approver' ? 'rgba(96,150,255,.18)' : 'rgba(255,255,255,.08)',
  color: role === 'admin' ? '#ffb27a' : role === 'approver' ? '#9cc0ff' : '#cfd6ea',
})
