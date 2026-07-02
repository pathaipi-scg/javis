import React, { useEffect, useState } from 'react'
import Navbar from './components/Navbar.jsx'
import Hero from './components/Hero.jsx'
import AskDemo from './components/AskDemo.jsx'
import CasePage from './components/CasePage.jsx'
import Features from './components/Features.jsx'
import Footer from './components/Footer.jsx'

// routing แบบ hash ง่ายๆ (ไม่ต้องลง react-router): #/ = landing, #/ask = ถาม, #/case = ป้อนเคส
function useRoute() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  if (hash.startsWith('#/ask')) return 'ask'
  if (hash.startsWith('#/case')) return 'case'
  return 'home'
}

export default function App() {
  const [audience, setAudience] = useState('biz')
  const route = useRoute()

  // ขึ้นหน้าใหม่ให้เลื่อนกลับบนสุด
  useEffect(() => { window.scrollTo(0, 0) }, [route])

  return (
    <div className="page">
      <div className="streaks">
        <div className="streak-glow" />
        <div className="streak-line" />
        <div className="streak-glow2" />
        <div className="grid" />
      </div>
      <Navbar />
      {route === 'home' && (
        <>
          <Hero audience={audience} setAudience={setAudience} />
          <Features />
        </>
      )}
      {route === 'ask' && <AskDemo />}
      {route === 'case' && <CasePage />}
      <Footer />
    </div>
  )
}
