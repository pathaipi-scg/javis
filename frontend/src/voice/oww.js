// ── openWakeWord wake listener (offline 100%, ฟรี, ไม่ signup) ────────────────
// จับคำปลุก "hey jarvis" ด้วยโมเดลเฉพาะทาง (ไม่ใช่ STT ทั่วไปแบบ Vosk ที่ถอดมั่ว)
// pipeline: เสียง 16k -> melspectrogram.onnx -> embedding_model.onnx -> hey_jarvis.onnx -> score
// ทุกอย่างรันในเบราว์เซอร์ (onnxruntime-web / WASM) เสียงไม่ออกเน็ต — ตัดเน็ตก็ยังทำงาน
//
// โมเดล openWakeWord v0.5.1 (public/models/oww/), wasm ของ ort (public/ort/) เสิร์ฟจากเครื่องเราเอง

const MODELS = {
  mel: '/models/oww/melspectrogram.onnx',
  emb: '/models/oww/embedding_model.onnx',
  ww: '/models/oww/hey_jarvis_v0.1.onnx',
}
const DEFAULT_THRESHOLD = 0.4   // score เกินนี้ = ปลุก (หลังแก้ให้เสียงต่อเนื่อง peak ควรสูงขึ้น — จูนได้)

// resample เสียงจาก inRate -> 16000 (linear) ให้ตรงกับที่ openWakeWord ต้องการ
// เบราว์เซอร์มักให้ 48000; ถ้าป้อน 48k เข้า pipeline ที่คิดว่า 16k -> feature เพี้ยนหมด
function resampleTo16k(input, inRate) {
  if (inRate === 16000) return input
  const ratio = 16000 / inRate
  const outLen = Math.round(input.length * ratio)
  const out = new Float32Array(outLen)
  for (let j = 0; j < outLen; j++) {
    const pos = j / ratio
    const i0 = Math.floor(pos), i1 = Math.min(i0 + 1, input.length - 1), f = pos - i0
    out[j] = input[i0] * (1 - f) + input[i1] * f
  }
  return out
}

let _ort = null
let _sessions = null

async function loadSessions() {
  if (!_sessions) {
    const ort = await import('onnxruntime-web')   // lazy: โหลด ~ ตอนเปิดโหมดเท่านั้น
    // ไม่ตั้ง wasmPaths -> ให้ Vite bundle wasm เป็น asset ของเราเอง (เสิร์ฟจาก origin เรา = ยัง offline)
    ort.env.wasm.numThreads = 1                   // เลี่ยง SharedArrayBuffer/COOP-COEP
    _ort = ort
    const opt = { executionProviders: ['wasm'] }
    const [mel, emb, ww] = await Promise.all([
      ort.InferenceSession.create(MODELS.mel, opt),
      ort.InferenceSession.create(MODELS.emb, opt),
      ort.InferenceSession.create(MODELS.ww, opt),
    ])
    _sessions = { mel, emb, ww }
  }
  return _sessions
}

// สร้างตัวฟังคำปลุก — คืน { start, stop }
// callbacks: onWake(score), onHeard(text) โชว์ score ไว้จูน, onReady(), onError(e)
export function createWakeListener({ onWake, onHeard, onReady, onError, threshold = DEFAULT_THRESHOLD, triggerFrames = 1 }) {
  let stream = null, ctx = null, node = null, source = null
  let stopped = false, draining = false, sessions = null
  const pending = []                 // คิวเสียง 16k (float)
  let audioWin = new Float32Array(0) // เสียงล่าสุดสำหรับ melspec (ต่อ context)
  let melBuf = []                    // mel frames (แต่ละอัน Float32Array(32)) เก็บ 76
  let embBuf = []                    // embeddings Float32Array(96) เก็บ 16
  let hitCount = 0                   // debounce: นับเฟรมติดกันที่ score เกิน threshold

  async function start() {
    stopped = false
    try {
      sessions = await loadSessions()
      if (stopped) return
      // ปิด DSP ของเบราว์เซอร์ (noiseSuppression/AGC/echoCancel) — มันบิดสเปกตรัมเสียง
      // ทำให้ feature ผิดจากที่ openWakeWord เทรน (เทรนบนเสียงดิบ) -> score เพี้ยน/ต่ำ
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      })
      if (stopped) { stream.getTracks().forEach(t => t.stop()); stream = null; return }
      // ใช้ native rate แล้ว resample เป็น 16k เอง — ไม่พึ่งว่าเบราว์เซอร์จะยอม 16k (บางตัวไม่ยอม -> เพี้ยน)
      ctx = new (window.AudioContext || window.webkitAudioContext)()
      const inRate = ctx.sampleRate
      console.log('[oww] mic sampleRate =', inRate, '-> resample เป็น 16000')
      source = ctx.createMediaStreamSource(stream)
      node = ctx.createScriptProcessor(2048, 1, 1)
      node.onaudioprocess = (e) => pushAudio(resampleTo16k(e.inputBuffer.getChannelData(0), inRate))
      source.connect(node)
      node.connect(ctx.destination)   // เราไม่เขียน output -> เงียบ ไม่มี echo
      onReady && onReady()
    } catch (e) {
      onError && onError(e)
      stop()
    }
  }

  function pushAudio(frame) {
    // ไมค์ให้ float [-1,1] แต่ openWakeWord เทรนบนเสียง int16 (±32768) -> ต้อง scale
    // ไม่งั้น melspec ได้ค่าจิ๋ว score ต่ำตลอด ไม่ปลุก
    for (let i = 0; i < frame.length; i++) pending.push(frame[i] * 32767)
    // ถ้า inference ตามไม่ทัน backlog บวม -> ทิ้งเสียงเก่า เก็บล่าสุด ~1s (กัน latency พุ่ง)
    if (pending.length > 24000) pending.splice(0, pending.length - 16000)
    drain()
  }

  // drain: ประมวลผลทีละ 1280 samples (80ms) "เรียงลำดับ ไม่ทิ้ง" -> mel/embedding ต่อเนื่อง
  // (ก่อนหน้านี้ skip ตอน busy ทำให้เสียงขาดช่วง 16-embedding ไม่ครบ score พีคแค่บางที)
  async function drain() {
    if (draining || stopped) return
    draining = true
    try {
      while (pending.length >= 1280 && !stopped) {
        const chunk = pending.splice(0, 1280)
        await step(chunk)
      }
    } finally {
      draining = false
    }
  }

  async function step(chunk) {
    try {
      const ort = _ort
      // audioWin = เสียงล่าสุด 1760 samples (1280 ใหม่ + 480 context -> ได้ ~8 mel frames)
      const merged = new Float32Array(audioWin.length + chunk.length)
      merged.set(audioWin); merged.set(chunk, audioWin.length)
      audioWin = merged.slice(-1760)
      if (audioWin.length < 1760) return   // warmup

      // 1) melspectrogram
      const melOut = await sessions.mel.run({ input: new ort.Tensor('float32', audioWin, [1, audioWin.length]) })
      const m = melOut.output, dims = m.dims, md = m.data
      const nmel = dims[dims.length - 1], frames = dims[dims.length - 2]
      const take = Math.min(8, frames)
      for (let f = frames - take; f < frames; f++) {
        const row = new Float32Array(nmel)
        for (let c = 0; c < nmel; c++) row[c] = md[f * nmel + c] / 10 + 2   // normalize ตาม openWakeWord
        melBuf.push(row)
        if (melBuf.length > 76) melBuf.shift()
      }
      if (melBuf.length < 76) return

      // 2) embedding จาก 76 mel frames -> [1,76,32,1]
      const embIn = new Float32Array(76 * nmel)
      for (let f = 0; f < 76; f++) embIn.set(melBuf[f], f * nmel)
      const embOut = await sessions.emb.run({ input_1: new ort.Tensor('float32', embIn, [1, 76, nmel, 1]) })
      const ed = embOut.conv2d_19.data
      const emb = new Float32Array(96)
      for (let i = 0; i < 96; i++) emb[i] = ed[i]
      embBuf.push(emb)
      if (embBuf.length > 16) embBuf.shift()
      if (embBuf.length < 16) return

      // 3) classifier [1,16,96] -> score
      const clsIn = new Float32Array(16 * 96)
      for (let i = 0; i < 16; i++) clsIn.set(embBuf[i], i * 96)
      const wwOut = await sessions.ww.run({ 'x.1': new ort.Tensor('float32', clsIn, [1, 16, 96]) })
      const score = wwOut['53'].data[0]
      onHeard && onHeard('score ' + score.toFixed(2))
      // debounce: ปลุกเมื่อ score เกิน threshold "ติดกัน" triggerFrames เฟรม (กันนอยส์พีควูบเดียว)
      if (score >= threshold) {
        hitCount++
        if (hitCount >= triggerFrames) { hitCount = 0; onWake && onWake(score) }
      } else {
        hitCount = 0
      }
    } catch (_) {
      // เฟรมเดียวพลาดไม่เป็นไร ฟังชิ้นถัดไปต่อ
    }
  }

  function stop() {
    stopped = true
    try { if (node) { node.onaudioprocess = null; node.disconnect() } } catch (_) { }
    try { source && source.disconnect() } catch (_) { }
    try { ctx && ctx.close() } catch (_) { }
    try { stream && stream.getTracks().forEach(t => t.stop()) } catch (_) { }
    node = source = ctx = stream = null
    pending.length = 0
    audioWin = new Float32Array(0)
    melBuf = []
    embBuf = []
  }

  return { start, stop }
}
