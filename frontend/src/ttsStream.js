// เล่นเสียง TTS แบบ streaming ผ่าน MediaSource — เล่นทันทีที่ chunk แรกมา (~1.6s) ไม่รอทั้งก้อน
// คืน Promise ที่ resolve ตอนเสียงจบ ; throw ถ้าทำไม่ได้ (ให้ผู้เรียก fallback เสียงเบราว์เซอร์)
export function playTtsStream(player, text) {
  return new Promise((resolve, reject) => {
    let settled = false
    const done = () => { if (!settled) { settled = true; resolve() } }
    const fail = (e) => { if (!settled) { settled = true; reject(e || new Error('tts-stream')) } }

    if (typeof MediaSource === 'undefined' || !MediaSource.isTypeSupported('audio/mpeg')) {
      return fail(new Error('no-mediasource'))       // เบราว์เซอร์ไม่รองรับ -> fallback
    }
    const ms = new MediaSource()
    player.src = URL.createObjectURL(ms)
    player.onended = done
    player.onerror = () => fail(new Error('audio-error'))

    ms.addEventListener('sourceopen', async () => {
      let sb
      try { sb = ms.addSourceBuffer('audio/mpeg') } catch (e) { return fail(e) }
      const queue = []
      let streamDone = false
      const flush = () => {
        if (sb.updating) return
        if (queue.length) { try { sb.appendBuffer(queue.shift()) } catch (e) { fail(e) } }
        else if (streamDone) { try { ms.endOfStream() } catch (e) {} }
      }
      sb.addEventListener('updateend', flush)
      try {
        const fd = new FormData(); fd.append('text', text)
        const res = await fetch('/api/tts-stream', { method: 'POST', body: fd })
        if (!res.ok || !res.body) return fail(new Error('bad-status'))
        const reader = res.body.getReader()
        player.play().catch(() => {})          // เริ่มเล่น (autoplay ผ่านเพราะ user gesture)
        for (;;) {
          const { value, done: d } = await reader.read()
          if (d) { streamDone = true; flush(); break }
          queue.push(value); flush()
        }
      } catch (e) { fail(e) }
    }, { once: true })
  })
}
