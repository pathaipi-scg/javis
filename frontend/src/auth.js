// auth.js — เก็บ token + แนบ Authorization ให้ทุก request /api/*
//
// ทำไมดัก window.fetch แทนแก้ทีละที่: หน้าเว็บเรียก /api/* อยู่ 28 จุดใน 11 ไฟล์
// (รวมเสียง TTS ใน ttsStream.js) — ดักที่เดียวคุมได้ครบ และ "ลืมไม่ได้"
// ถ้าไปแก้ทีละจุด วันหลังเพิ่ม fetch ใหม่แล้วลืมแนบ token = พังเงียบๆ

const KEY = 'jarvis_token'   // localStorage: refresh หน้าแล้วยัง login อยู่

export const getToken = () => localStorage.getItem(KEY) || ''
export const setToken = (t) => localStorage.setItem(KEY, t)
export const clearToken = () => localStorage.removeItem(KEY)

// ให้ App รู้ตอนโดนเด้ง (token หมดอายุ/ถูกถอน) -> เด้งกลับหน้า login
let _onUnauthorized = () => { }
export function setOnUnauthorized(fn) { _onUnauthorized = fn }

let _installed = false

export function installAuthFetch() {
  if (_installed) return           // StrictMode เรียก effect ซ้ำ — กันซ้อน fetch หลายชั้น
  _installed = true
  const origFetch = window.fetch.bind(window)

  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || ''
    const isApi = url.startsWith('/api/')            // เฉพาะ API ของเราเอง (path เดียวกัน)
    const isLogin = url.startsWith('/api/login')     // login ยังไม่มี token — ไม่ต้องแนบ
    if (!isApi || isLogin) return origFetch(input, init)

    const token = getToken()
    let opts = init
    if (token) {
      const headers = new Headers((init && init.headers) || (typeof input !== 'string' ? input.headers : undefined))
      headers.set('Authorization', 'Bearer ' + token)
      opts = { ...(init || {}), headers }
    }
    const res = await origFetch(input, opts)
    if (res.status === 401) {   // token เสีย/หมดอายุ -> ล้างทิ้ง เด้งไปหน้า login
      clearToken()
      _onUnauthorized()
    }
    return res
  }
}

export async function login(username, password) {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || 'login ไม่สำเร็จ')
  setToken(data.access_token)
  return data
}

// เช็คว่า token ที่เก็บไว้ยังใช้ได้ไหม (เรียกตอนเปิดหน้า) — คืน user หรือ null
export async function fetchMe() {
  if (!getToken()) return null
  try {
    const res = await fetch('/api/me')
    if (!res.ok) return null
    return await res.json()
  } catch (_) {
    return null
  }
}

export function logout() {
  clearToken()
  _onUnauthorized()
}
