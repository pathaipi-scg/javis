import React, { useEffect, useState } from 'react'
import Navbar from './components/Navbar.jsx'
import Landing from './components/Landing.jsx'
import AskDemo from './components/AskDemo.jsx'
import CasePage from './components/CasePage.jsx'
import SearchPage from './components/SearchPage.jsx'
import DashboardPage from './components/DashboardPage.jsx'
import SttPage from './components/SttPage.jsx'
import GraphPage from './components/GraphPage.jsx'
import Footer from './components/Footer.jsx'

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
  if (hash.startsWith('#/ask')) return 'ask'
  if (hash.startsWith('#/case')) return 'case'
  if (hash.startsWith('#/search')) return 'search'
  if (hash.startsWith('#/graph')) return 'graph'
  if (hash.startsWith('#/dashboard')) return 'dashboard'
  if (hash.startsWith('#/stt')) return 'stt'
  return 'home'
}

export default function App() {
  const route = useRoute()

  // ขึ้นหน้าใหม่ให้เลื่อนกลับบนสุด
  useEffect(() => { window.scrollTo(0, 0) }, [route])

  // หน้า graph เต็มจอ มี topbar ของตัวเอง — ไม่ใช้ Navbar/Footer ของแอพ
  if (route === 'graph') return <GraphPage />

  return (
    <div className="page">
      <div className="streaks">
        <div className="streak-glow" />
        <div className="streak-line" />
        <div className="streak-glow2" />
        <div className="grid" />
      </div>
      <Navbar />
      {route === 'home' && <Landing />}
      {route === 'ask' && <AskDemo />}
      {route === 'case' && <CasePage />}
      {route === 'search' && <SearchPage />}
      {route === 'dashboard' && <DashboardPage />}
      {route === 'stt' && <SttPage />}
      <Footer />
    </div>
  )
}
