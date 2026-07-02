import React, { useState } from 'react'
import Navbar from './components/Navbar.jsx'
import Hero from './components/Hero.jsx'
import AskDemo from './components/AskDemo.jsx'
import Features from './components/Features.jsx'
import Footer from './components/Footer.jsx'

export default function App() {
  const [audience, setAudience] = useState('biz')
  return (
    <div className="page">
      <div className="streaks">
        <div className="streak-glow" />
        <div className="streak-line" />
        <div className="streak-glow2" />
        <div className="grid" />
      </div>
      <Navbar />
      <Hero audience={audience} setAudience={setAudience} />
      <AskDemo audience={audience} />
      <Features />
      <Footer />
    </div>
  )
}
