import React, { useEffect, useState } from 'react'
import Navbar from './components/Navbar.jsx'
import Landing from './components/Landing.jsx'
import CasePage from './components/CasePage.jsx'
import SearchPage from './components/SearchPage.jsx'
import DashboardPage from './components/DashboardPage.jsx'
import BubblePage from './components/BubblePage.jsx'
import SttPage from './components/SttPage.jsx'
import GraphPage from './components/GraphPage.jsx'
import Footer from './components/Footer.jsx'
import VoiceNav from './components/VoiceNav.jsx'

// routing แบบ hash ง่ายๆ (ไม่ต้องลง react-router)
// #/ = landing (HUD), #/ask = ถาม, #/case = ป้อนเคส, #/search = ค้นเคส,
// #/graph = knowledge graph, #/dashboard = สรุป
function useRoute() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  if (hash.startsWith('#/case')) return 'case'
  if (hash.startsWith('#/search')) return 'search'
  if (hash.startsWith('#/graph')) return 'graph'
  if (hash.startsWith('#/dashboard')) return 'dashboard'
  if (hash.startsWith('#/stats')) return 'stats'
  if (hash.startsWith('#/stt')) return 'stt'
  return 'home'
}

export default function App() {
  const route = useRoute()

  // โมเดลที่ใช้ตอบ — ถือที่ App เพื่อให้ Navbar เลือกได้ (dropdown อยู่มุมขวาบน)
  // แต่ Landing เป็นตัวใช้ค่าตอนถาม
  const [models, setModels] = useState({ local: [], api: [] })
  const [model, setModel] = useState('')
  useEffect(() => {
    fetch('/api/models').then(r => r.json()).then(d => {
      setModels({ local: d.local || [], api: d.api || [] })
      // default = GPT (Azure api) ถ้ามี; ไม่มีค่อยตก default backend / local ตัวแรก
      setModel(d.api?.[0]?.id || d.default || d.local?.[0]?.id || '')
    }).catch(() => {})
  }, [])

  // ขึ้นหน้าใหม่ให้เลื่อนกลับบนสุด
  useEffect(() => { window.scrollTo(0, 0) }, [route])

  // ตัวเนื้อหาหน้า (สลับตาม route)
  let body
  if (route === 'graph') {
    body = <GraphPage />                       // หน้าเต็มจอ มี topbar เอง
  } else if (route === 'dashboard') {
    body = <BubblePage model={model} />        // หน้าเต็มจอ มี topbar เอง
  } else {
    body = (
      <div className="page">
        <div className="streaks">
          <div className="streak-glow" />
          <div className="streak-line" />
          <div className="streak-glow2" />
          <div className="grid" />
        </div>
        <Navbar models={models} model={model} setModel={setModel} />
        {route === 'home' && <Landing model={model} />}
        {route === 'case' && <CasePage />}
        {route === 'search' && <SearchPage />}
        {route === 'stats' && <DashboardPage />}
        {route === 'stt' && <SttPage />}
        <Footer />
      </div>
    )
  }

  // VoiceNav อยู่ตำแหน่ง (root fragment, child[0], key คงที่) เดิมทุก route
  // -> React ไม่ remount เวลาเปลี่ยนหน้า = ไมค์/wake ฟังต่อเนื่องข้ามหน้าได้จริง
  return (
    <>
      <VoiceNav key="voicenav" route={route} model={model} />
      {body}
    </>
  )
}
