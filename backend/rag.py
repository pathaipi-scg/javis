"""
ค้นหา + ถาม-ตอบ (RAG) จากเคสใน Obsidian vault จริง

ชั้นการทำงาน (graceful degradation เหมือน transcribe.py/llm.py):
  1. อ่านเคสจาก vault (history rows ในไฟล์ machines/machine-*.md)
  2. ฝังเวกเตอร์ด้วย bge-m3 ผ่าน Ollama (OpenAI-compatible /v1/embeddings)
  3. ค้นด้วย cosine similarity (numpy) — vault เล็กไม่ต้องใช้ FAISS
     (โตแล้วค่อยสลับ index เป็น FAISS โดยไม่ต้องแก้ส่วนอื่น)
  4. ตอบคำถาม = ดึงเคสที่เกี่ยว -> ให้ Typhoon สรุป + อ้างอิง case_id
ถ้า embeddings/LLM ต่อไม่ได้ หรือ vault ว่าง -> คืน None ให้ app.py ตกไป mock
"""
import os, re, math
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

VAULT_PATH  = os.getenv("VAULT_PATH", "").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
# เกณฑ์ cosine ขั้นต่ำ (%) แบบ 2 ระดับ (hybrid router — เลือกตามว่าคำถามมี "ศัพท์ช่าง" ไหม):
#   คำถามมีศัพท์ช่าง (มอเตอร์/แบริ่ง/รั่ว/ชื่อเครื่องใน vault ฯลฯ) -> เกณฑ์ต่ำ:
#     คำถามอ้อมๆ ที่ cosine ไม่สูงก็ยังผ่านไปให้ LLM ตอบ (ลูกปืนมีเสียง=51, แบริ่ง=44)
#   คำถามไม่มีศัพท์ช่าง (ทักทาย/คุยเล่น/เรื่องทั่วไป) -> เกณฑ์สูง:
#     กันขาด เพราะพื้น cosine ของข้อความไทยไม่เกี่ยวกันก็แตะ ~40 ได้ (สวัสดี=42)
# ตัวเช็คศัพท์เป็น string match ในเครื่อง 0ms — ไม่เพิ่มเวลาตอบ
REL_MIN_DOMAIN = int(os.getenv("RAG_REL_MIN_DOMAIN", "35"))
REL_MIN_OTHER  = int(os.getenv("RAG_REL_MIN", "48"))
# เกณฑ์เฉพาะหน้า "ค้นเคส" (semantic search) — ผ่อนกว่า ask เพราะเป็นการค้นเชิงสำรวจ + พิมพ์สด
# วัดจริง: พิมพ์ไม่จบ "มอเตอ"=43 "คอมเพรส"=46 "สายพา"=51 (ควรเจอ) ; มั่ว "เนเร่พ..."=25 (ไม่ควร)
# in-domain (เจอ/เป็นต้นศัพท์ช่าง) 33, นอกโดเมน 40 -> พิมพ์ไม่จบยังเจอ แต่มั่วหลุด
SEARCH_MIN_DOMAIN = int(os.getenv("RAG_SEARCH_MIN_DOMAIN", "33"))
SEARCH_MIN_OTHER  = int(os.getenv("RAG_SEARCH_MIN", "40"))
# คำที่บ่งว่า LLM ตอบว่า "ไม่พบ" -> ล้าง citation ทิ้ง (โมเดลเห็นเองว่า context ไม่เกี่ยว)
_NOT_FOUND_RE = re.compile(r"ไม่พบ|ไม่มีเคส|ไม่ตรง|ไม่เกี่ยวข้อง|ข้อมูลไม่พอ|ไม่มีข้อมูล")
# เวอร์ชันอังกฤษของ "ไม่พบ" — เลนอังกฤษไม่มีคำไทยให้ _NOT_FOUND_RE จับ
_EN_NOT_FOUND_RE = re.compile(r"\bno\b.{0,40}\b(case|match|matching|relevant|data|record)\b", re.I)
# คำที่บ่งว่าคำตอบ "มีคำแนะนำจริง" -> ถึงจะขึ้นต้นว่า "ไม่พบเคสตรง" ก็ยังอ้างเคสได้
# (กันเคสตอบดีแบบผสม "ไม่พบตรงเป๊ะ แต่ถ้าหมายถึง X วิธีแก้คือ..." โดนตัด citation ทิ้ง)
_ADVICE_RE = re.compile(r"วิธีแก้|ควร|แนะนำ|ตรวจ|เปลี่ยน|ปรับ|เติม|อัด|ไล่ลม|ทำความสะอาด")
# วลีปฏิเสธหนักแน่น -> บังคับตัด citation เสมอ ต่อให้มีคำอย่าง "วิธีแก้" ปนอยู่ในประโยคปฏิเสธ
# (กันเคส "ไม่สามารถระบุวิธีแก้ไขได้" ที่คำว่า 'วิธีแก้' ไปหลอก _ADVICE_RE ให้แนบเคสมั่ว)
_STRONG_REJECT_RE = re.compile(r"ไม่สามารถ(ระบุ|ตอบ|ให้)|ไม่มีข้อมูลเกี่ยว|ไม่พบข้อมูล|ไม่เกี่ยวข้องกับ")
# marker ของ "ข้อมูลเคสดิบ" ที่ไม่ควรโผล่ในคำตอบ -> ถ้าเจอแปลว่าโมเดลลอก context มา
# ต้องตรงกับ header ดิบจริง (มี colon) เท่านั้น — ไม่งั้นชนสำนวนธรรมชาติ เช่น "พบเคสที่เกี่ยวข้องกับ..."
# รหัสเคสรองรับทั้งแบบเดิม MTN-2026-0001 และแบบหลายเคส/ไฟล์ MTN-080726-01 / MTN-190626
_DUMP_RE = re.compile(r"\[MTN-\d+(-\d+)?\]|เคสที่เกี่ยวข้อง:|ฝ่าย:\s|อาการ:\s")
# ตอนตาข่ายเด้ง: เอาเฉพาะเคสที่คะแนนห่างจากตัวท็อปไม่เกินค่านี้ (กันลากเคสคนละเรื่องมาปน)
_FALLBACK_MARGIN = int(os.getenv("RAG_FALLBACK_MARGIN", "6"))


def _looks_like_dump(text):
    """เดาว่าคำตอบเป็นการ 'ลอกข้อมูลเคสดิบ' ไหม (โมเดลตัวเล็กชอบทำ)"""
    return bool(_DUMP_RE.search(text or ""))


def _is_english(q):
    """คำถามเป็นภาษาอังกฤษไหม = ไม่มีอักษรไทยเลย แต่มีอักษรอังกฤษ
    ใช้ตัดสินภาษาคำตอบ (ถามอังกฤษ -> ตอบอังกฤษ) แบบ deterministic ไม่พึ่งโมเดลเดา"""
    q = q or ""
    return (not re.search("[฀-๿]", q)) and bool(re.search(r"[A-Za-z]", q))


# คำเชื่อมอังกฤษล้วน (function word) — ตัวชี้ว่าเป็น "ประโยคอังกฤษ" จริง
# ห้ามใส่ศัพท์โดเมน (downtime/severity/case) เพราะคำตอบไทยยืมมาใช้ปกติ
_EN_PROSE_RE = re.compile(r"\b(the|is|are|was|were|be|been|has|have|had|with|without|"
                          r"from|there|this|these|those|which|and|or|of|to|in|for|by|it|as)\b", re.I)


def _is_thai_answer(text):
    """คำตอบเป็นภาษาไทยไหม — ใช้คู่กับ _is_english(query) เช็คว่าตอบผิดภาษาไหม

    ห้ามเช็คแค่ "มีอักษรไทยไหม" (โค้ดเดิมทำแบบนั้น): ชื่อเครื่องใน vault เป็นไทย
    (รถตัด, ปั๊มน้ำ, หุ่นยนต์จับแผ่นกระเบื้อง) พอโผล่ในคำตอบแค่คำเดียวก็นับเป็น
    "คำตอบไทย" ทันที ทั้งที่เนื้อเป็นอังกฤษล้วน -> ตาข่ายบังคับภาษาไม่ทำงาน
    ผลอีกด้าน: คำตอบอังกฤษที่ลิสต์เครื่องชื่อไทยหลายตัว (เช่นเลนวิเคราะห์ 13 เคส)
    เคยถูกตัดสินว่าเป็นไทยแล้วโดนแปลซ้ำ -> เสี่ยงรายการเคสหล่นระหว่างแปล

    ตัดสินจาก 2 ทาง (ทางใดทางหนึ่งผ่าน = ไทย):
      1. สัดส่วนอักษรไทย >= ครึ่ง                 -> ไทยชัดเจน
      2. ไม่มีคำเชื่อมอังกฤษ (the/is/with/...)   -> ไทยที่มีศัพท์อังกฤษปนเยอะ
         เช่น "พบ 13 เคส: Motor M-101 (เคส MTN-2026-0005) 120 นาที" ไทยแค่ 43%
         แต่ไม่มีคำเชื่อม = ไทย -> กันแปลซ้ำโดยไม่จำเป็น (แปลซ้ำเสี่ยงรายการเคสหล่น)
    """
    text = text or ""
    th = len(re.findall(r"[฀-๿]", text))
    if not th:
        return False                       # ไม่มีอักษรไทยเลย = ไม่ใช่ไทยแน่นอน
    la = len(re.findall(r"[A-Za-z]", text))
    return (th / (th + la) >= 0.5) or (len(_EN_PROSE_RE.findall(text)) <= 1)


# ตาข่ายกันมโน: คำตอบต้องมีเนื้อมาจากเคสจริง ไม่ใช่ความรู้ทั่วไปที่โมเดลจำมาตอนเทรน
# วัดด้วย char-trigram overlap: คำตอบที่ย่อยจากเคสวัดได้ ~0.54, คำตอบมโนวัดได้ ~0.06 -> 0.25 กลางช่อง
GROUND_MIN = float(os.getenv("RAG_GROUND_MIN", "0.25"))
# เพดานจำนวนเคสที่ป้อน LLM ในเลนวิเคราะห์ (นับ/สรุป/จัดอันดับ) — ต้องใหญ่พอให้เห็นเคสครบ
# ถ้า vault โตเกินนี้มาก ควรกรอง deterministic ก่อน (topic/metric) แทนป้อนดิบทั้งหมด
_ANALYTIC_MAX = int(os.getenv("RAG_ANALYTIC_MAX", "200"))


def _trigrams(s):
    s = "".join((s or "").split())
    return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) > 2 else set()


def _groundedness(answer_text, ctx):
    """สัดส่วน trigram ของคำตอบที่พบใน ctx (0..1) — ต่ำ = เนื้อคำตอบไม่ได้มาจากเคส (มโน)"""
    ta = _trigrams(answer_text)
    return len(ta & _trigrams(ctx)) / len(ta) if ta else 0.0


def _is_reject(text, en):
    """คำตอบเป็นการปฏิเสธ 'ไม่พบเคส' ไหม — ไทยจับด้วย _NOT_FOUND_RE, อังกฤษด้วย _EN_NOT_FOUND_RE"""
    return bool((_EN_NOT_FOUND_RE if en else _NOT_FOUND_RE).search(text or ""))


def _to_thai(text, model):
    """แปลข้อความเป็นไทย (คงชื่อเครื่อง/รหัส/ตัวเลข). แปลไม่ได้ -> คืนต้นฉบับ
    ใช้เทียบ trigram กับ ctx ไทย (ทั้ง groundedness และเลือก citation)"""
    try:
        th = _llm_chat(
            [{"role": "system", "content": "แปลข้อความเป็นภาษาไทย ตอบเฉพาะคำแปล "
                                           "คงชื่อเครื่อง/รหัส/ตัวเลขไว้ (เช่น V-203, 6206)"},
             {"role": "user", "content": text}], model)
        return th.strip() if (th and len(th.strip()) > 3) else text
    except Exception:
        return text   # แปลไม่ได้ -> ต้นฉบับ (overlap ต่ำ -> ปลอดภัยกว่าปล่อยมโน/แปะมั่ว)


def _grounded_score(text, ctx, en, model):
    """groundedness ข้ามภาษา: ctx เป็นไทยเสมอ -> คำตอบอังกฤษต้องแปลกลับไทยก่อนวัด
    (trigram อังกฤษ-ไทย overlap ~0 เสมอ วัดตรงๆ จะ reject คำตอบอังกฤษที่ถูกต้องทิ้งหมด)"""
    return _groundedness(_to_thai(text, model) if en else text, ctx)


def _best_citation(text, rel_hits, en=False, model=None):
    """เลือกเคสที่ 'คำตอบใช้จริง' แทนการแปะ rel_hits[0] ดื้อๆ (ที่ทำ citation ผิดตัว)
    1) ชื่อเครื่องของเคสโผล่ในคำตอบ -> เคสนั้น (แม่นสุด; อังกฤษก็ได้ เพราะชื่อเครื่อง/รหัสคงรูป)
    2) ไม่เอ่ยชื่อ -> เคสที่เนื้อหาทับกับคำตอบมากสุด (groundedness)
       อังกฤษ: แปลคำตอบกลับไทยก่อนเทียบ (ไม่งั้น overlap=0 ทุกเคส -> ตก rel_hits[0] ผิดตัว)
    3) วัดไม่ได้ -> ตกมา rel_hits[0] เดิม"""
    if not rel_hits:
        return None
    low = (text or "").casefold()
    for h in rel_hits:
        m = (h.get("machine") or "").strip().casefold()
        if m and m in low:
            return h
    probe = _to_thai(text, model) if en else text
    best = max(rel_hits, key=lambda h: _groundedness(probe, _case_ctx([h])))
    return best if _groundedness(probe, _case_ctx([best])) > 0 else rel_hits[0]
# embeddings/LLM ใช้ Ollama ตัวเดียวกับ llm.py (OpenAI-compatible)
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "http://localhost:11434/v1")
QWEN_API_KEY  = os.getenv("QWEN_API_KEY", "not-needed")

# ---- Azure OpenAI (โมเดลคลาวด์ เช่น gpt-5.4-mini ซื้อผ่าน Azure) ----
AZURE_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
AZURE_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
AZURE_READY      = bool(AZURE_ENDPOINT and AZURE_API_KEY and AZURE_DEPLOYMENT)


def default_model():
    """โมเดลที่ใช้เมื่อผู้ใช้ไม่ได้เลือก — Azure ถ้าตั้ง .env ครบ, ไม่งั้นตกมา local

    ทำไม Azure: วัดกับคำถามชุด Desktop/test-questions.txt แล้ว Azure เร็วกว่า
    (~1.5-2.0 วิ เทียบ Typhoon ~2.9-3.6 วิ) และเอ่ย case_id ในคำตอบ -> citation
    เกาะเคสที่ใช้จริงได้แม่นกว่า ส่วนคำตอบ Typhoon มักโดนตาข่ายกันดิบ/กันมโนตีตก
    แล้วตกไปใช้ข้อความ fallback สำเร็จรูป ("พบ N เคสในระบบ: ...") ที่ไม่มี case_id
    -> คนที่ไม่แตะ dropdown ไม่ควรเจอเลนที่ด้อยกว่า

    *** ที่เดียวที่ตัดสิน default *** — ทั้ง rag.answer() และ app._model_options()
    ต้องเรียกตัวนี้ ห้ามเขียน fallback ซ้ำที่อื่น (เคยแตกกันมาแล้ว: dropdown โชว์ Azure
    แต่ /api/ask ที่ไม่ส่ง model กลับวิ่งเข้า Typhoon)
    """
    from llm import QWEN_MODEL
    return f"azure:{AZURE_DEPLOYMENT}" if AZURE_READY else QWEN_MODEL

# ---- n8n proxy lane — ยิงผ่าน webhook n8n (ในวงบริษัท) แทนเรียก Azure ตรงจากแอป ----
# n8n ถือ API key เอง (ไม่โผล่ในแอป) + คุมกลาง/log/rate-limit ได้ที่เดียว
# ข้อมูลยังออกไป Azure OpenAI ของบริษัทเหมือนเดิม — n8n แค่กัน key รั่ว + เป็นจุดคุม
# ตั้งแค่ URL webhook ใน .env (ไม่มี secret ในโค้ด) เช่น http://<n8n-host>/webhook/ask_javis
N8N_ASK_URL = os.getenv("N8N_ASK_URL", "").strip()
# กัน slash เกิน (เช่น :1889//webhook) ที่ทำ n8n ตอบ 404 — ยุบ // ที่ไม่ใช่หลัง scheme
N8N_ASK_URL = re.sub(r"(?<!:)//+", "/", N8N_ASK_URL)
N8N_READY   = bool(N8N_ASK_URL)

# ---- Reranker (cross-encoder) — ตัวเช็คซ้ำว่าเคสที่ bge-m3 คัดมา "เกี่ยวกับคำถามจริงไหม" ----
# bge-m3 (bi-encoder) วัดได้แค่หัวข้อคล้าย -> "แอร์ออฟฟิศ" ชน "Air Compressor" ได้คะแนนสูงผิดๆ
# cross-encoder อ่านคำถาม+เคสพร้อมกัน แยกเกี่ยว/ไม่เกี่ยวได้คมกว่ามาก (0.85 vs 0.05)
# รันบน CPU (GPU เต็มแล้ว: Typhoon+bge+whisper) — งานเบา ให้คะแนนแค่ ~10 คู่/คำถาม
# เลือก mmarco-mini (118M): เทสต์จริงบนชุด 13 คำถาม — เร็วกว่า bge-reranker-v2-m3 (568M) 11 เท่า
# (~170ms vs ~2000ms/คำถาม บน CPU) และแยกเกี่ยว/ไม่เกี่ยวคมกว่า (22x vs 3.7x)
RERANK_MODEL = os.getenv("RAG_RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
# เกณฑ์ตัด (สเกล sigmoid 0..1): เกี่ยวจริงต่ำสุดวัดได้ 0.14 / ไม่เกี่ยวสูงสุด 0.097
# (เคสความปลอดภัย 0015 หลุดมาตอนถาม "เฉพาะฝ่าย CB มอเตอร์ร้อน" เพราะคำว่า CB ตรงกัน)
# -> 0.12 ตัดตัวหลอกพวกนั้นทิ้ง; ไม่มีเคสผ่าน = ตอบ "ไม่พบ" ทันที ไม่เรียก LLM (กันมโนที่ต้นทาง)
RERANK_MIN   = float(os.getenv("RAG_RERANK_MIN", "0.12"))  # ต่ำกว่านี้ = ไม่เกี่ยว ตัดทิ้ง
_RERANKER = {"model": None, "failed": False}


def _get_reranker():
    """โหลด cross-encoder ครั้งแรกครั้งเดียว; ถ้า lib/โมเดลไม่มี -> None (ตกไปใช้ gate แบบเดิม)"""
    if _RERANKER["failed"]:
        return None
    if _RERANKER["model"] is None:
        try:
            from sentence_transformers import CrossEncoder
            _RERANKER["model"] = CrossEncoder(RERANK_MODEL, device="cpu", max_length=512)
            print(f"[RAG] reranker พร้อมใช้ ({RERANK_MODEL} บน CPU)")
        except Exception as e:
            print(f"[RAG] โหลด reranker ไม่ได้ ({type(e).__name__}: {e}) -> ใช้ gate คะแนน embed แบบเดิม")
            _RERANKER["failed"] = True
            return None
    return _RERANKER["model"]


def _rerank(query, hits):
    """ให้คะแนน 'เกี่ยวจริง' 0..1 ต่อเคส (อ่านคำถาม+เคสคู่กัน). คืน list[float] หรือ None ถ้าใช้ไม่ได้"""
    rr = _get_reranker()
    if rr is None or not hits:
        return None
    try:
        # passage ใส่ label ไทยให้อ่านเป็นเรื่องราว — cross-encoder แยกเกี่ยว/ไม่เกี่ยวแม่นขึ้นชัด
        pairs = [(query, f"เครื่อง {h.get('machine','')} อาการ: {h.get('symptom','')} "
                         f"สาเหตุ: {h.get('cause','')} วิธีแก้: {h.get('solution','')}") for h in hits]
        scores = [float(s) for s in rr.predict(pairs)]
        # บางโมเดลคืน logit ดิบ (นอกช่วง 0..1) บางโมเดลผ่าน sigmoid มาแล้ว -> ทำให้เป็น 0..1 เสมอ
        if any(s < 0 or s > 1 for s in scores):
            scores = [1.0 / (1.0 + math.exp(-s)) for s in scores]
        return scores
    except Exception as e:
        print(f"[RAG] rerank ล้มเหลว ({type(e).__name__}: {e}) -> ใช้ gate แบบเดิม")
        return None


# คีย์เวิร์ดไทย -> tag (ใช้ derive tag จากข้อความ ตราบที่ผู้ใช้ยังไม่กรอก tag เอง)
_TAG_RULES = [
    ("hydraulic", ["ไฮดรอลิก", "แรงดัน", "น้ำมัน"]),
    ("motor",     ["มอเตอร์"]),
    ("pump",      ["ปั๊ม", "ปั้ม"]),
    ("electrical",["ไฟ", "ไหม้", "ลัดวงจร", "เขม่า"]),
    ("bearing",   ["แบริ่ง", "ลูกปืน"]),
    ("belt",      ["สายพาน"]),
    ("valve",     ["วาล์ว"]),
    ("leak",      ["รั่ว", "ซึม"]),
    ("sensor",    ["เซนเซอร์", "เซ็นเซอร์", "sensor"]),
    ("overheat",  ["ร้อน", "ความร้อน"]),
]


def _derive_tags(text):
    tags = [tag for tag, kws in _TAG_RULES if any(k in text for k in kws)]
    return tags or ["general"]


_TAG_KWS = dict(_TAG_RULES)   # tag -> คำไทย synonyms (lookup เร็ว)


def _query_topics(query):
    """หา 'หัวข้อ' ที่คำถามพูดถึง จาก _TAG_RULES — คืน set ของ tag
    จับทั้งชื่อ tag อังกฤษ (bearing/motor/pump...) และคำไทย synonym (แบริ่ง/ลูกปืน...)"""
    q = (query or "").casefold()
    topics = set()
    for tag, kws in _TAG_RULES:
        if re.search(rf"(?<![a-z]){re.escape(tag)}(?![a-z])", q) or any(k.casefold() in q for k in kws):
            topics.add(tag)
    return topics


def _case_matches_topics(c, topics):
    """เคสเกี่ยวกับหัวข้อที่ถามจริงไหม — เช็คจาก tags ของเคส + ข้อความเคส (machine/component/อาการ/สาเหตุ/วิธีแก้)
    deterministic ทั้งหมด (ไม่พึ่ง LLM) -> การันตีว่าเคสที่คัดมา 'มีของจริง' ตรงหัวข้อ"""
    if topics & {t.casefold() for t in (c.get("tags") or [])}:
        return True
    blob = " ".join(str(c.get(f, "")) for f in ("machine", "component", "symptom", "cause", "solution")).casefold()
    for tag in topics:
        if tag in blob or any(k.casefold() in blob for k in _TAG_KWS.get(tag, [])):
            return True
    return False


# เงื่อนไข severity ที่ถามถึง — ต้องมีบริบทคำว่า severity/รุนแรง ไม่ใช่เจอคำว่า high ลอยๆ
# (กัน "highest downtime" โดนตีความเป็น severity=high)
_SEVERITY_RES = [
    ("high",   re.compile(r"high[\s-]*severity|severity[\s:=]*high|เคส\s*high|"
                          r"(ความ)?รุนแรง\s*สูง|ระดับ(ความรุนแรง)?\s*สูง|severity\s*สูง", re.I)),
    ("medium", re.compile(r"medium[\s-]*severity|severity[\s:=]*medium|เคส\s*medium|"
                          r"(ความ)?รุนแรง\s*(ปาน)?กลาง|severity\s*กลาง", re.I)),
    ("low",    re.compile(r"low[\s-]*severity|severity[\s:=]*low|เคส\s*low|"
                          r"(ความ)?รุนแรง\s*ต่ำ|severity\s*ต่ำ", re.I)),
]
# "เกิน/มากกว่า/over N" — ใช้ได้เมื่อคำถามพูดถึงเวลาหยุดเครื่องเท่านั้น
_DOWNTIME_GT_RE = re.compile(r"(?:เกิน|มากกว่า|over|more than|>)\s*(\d+)", re.I)
_DOWNTIME_CTX_RE = re.compile(r"downtime|นาที|\bmin(ute)?s?\b|หยุดเครื่อง|เสียเวลา", re.I)

# ชื่อฝ่าย/โรงงานที่เป็น "คำทั่วไป" ในโดเมนนี้ -> เจอลอยๆ ไม่ถือว่าตั้งใจกรอง ต้องมีคำนำหน้า
# (ฝ่ายจริงชื่อ Maintenance/Production/Utility ชนคำอังกฤษปกติ เช่น "maintenance cases")
_AMBIGUOUS_NAMES = {"maintenance", "production", "utility", "test", "general", "service"}
_DEPT_CUE_RE  = re.compile(r"ฝ่าย|แผนก|\bdept\b|\bdepartment\b", re.I)
_PLANT_CUE_RE = re.compile(r"โรงงาน|\bplant\b", re.I)


def _parse_filters(query):
    """อ่านเงื่อนไข metric จากคำถาม -> dict (deterministic ไม่พึ่ง LLM)
    รองรับ: severity (high/medium/low), downtime_gt (เกิน N นาที)
    ไม่เจอเงื่อนไข -> {} = ไม่กรอง (พฤติกรรมเดิม)"""
    q = query or ""
    f = {}
    for level, rx in _SEVERITY_RES:
        if rx.search(q):
            f["severity"] = level
            break
    m = _DOWNTIME_GT_RE.search(q)
    if m and _DOWNTIME_CTX_RE.search(q):     # ต้องมีบริบทเวลา ไม่งั้น "เกิน 60" อาจหมายถึงอย่างอื่น
        f["downtime_gt"] = int(m.group(1))
    return f


def _match_filters(c, f):
    """เคสผ่านเงื่อนไข metric ไหม (ใช้ค่าใน frontmatter ตรงๆ — เป๊ะ ไม่ให้ LLM เดา)"""
    if "severity" in f and (c.get("severity") or "").strip().casefold() != f["severity"]:
        return False
    if "downtime_gt" in f:
        try:
            dt = int(c.get("downtime_min") or 0)
        except (TypeError, ValueError):
            dt = 0
        if dt <= f["downtime_gt"]:
            return False
    return True


def _lexical_hits(query, hits):
    """fallback ตอน reranker ตัดหมด: เก็บเคสที่ 'ชื่อ/แท็กตรงกับคำในคำถาม' (keyword lookup)
    reranker เก่งกับประโยคคำถาม แต่ให้คะแนนคำเดี่ยว/คำที่ STT ถอดเพี้ยนต่ำ -> เลนนี้กู้คืน
    'แอร์ในออฟฟิศ' ไม่ตรงแท็ก/ชื่อเครื่องเคสไหน -> ยังถูกปฏิเสธ (ไม่หลุด false positive)"""
    qtags = set(_derive_tags(query)) - {"general"}
    qwords = {w.casefold() for w in re.split(r"[\s\-_/]+", query) if len(w) >= 3}
    out = []
    for h in hits:
        htags = {t.casefold() for t in h.get("tags", [])}
        fields = f"{h.get('machine','')} {h.get('component','')}".casefold()
        if (qtags & htags) or any(w in htags or w in fields for w in qwords):
            out.append(h)
    return out


# แท็กยอดนิยมตั้งต้น (โชว์เป็น chip ให้คลิก) — ผู้ใช้เพิ่มเองได้
SEED_TAGS = ["hydraulic", "motor", "pump", "electrical", "bearing", "belt",
             "valve", "leak", "pressure-drop", "overheat", "vibration",
             "sensor", "pneumatic", "lubrication", "alignment"]


def all_tags():
    """รวมแท็ก seed + แท็กที่เคยใช้ในเคสจริง (ไม่ซ้ำ) — ป้อนให้ฟอร์มทำ chip เลือก"""
    used = set()
    for c in load_cases():
        for t in c.get("tags", []):
            used.add(t)
    extra = sorted(used - set(SEED_TAGS))
    return SEED_TAGS + extra


# ---------- อ่านเคสจาก vault ----------
def _parse_machine_file(path):
    """ดึง history rows จาก machines/machine-X.md -> list ของ case dict"""
    txt = path.read_text(encoding="utf-8")
    name = "?"
    m = re.search(r"^machine:\s*(.+)$", txt, re.M)
    if m:
        name = m.group(1).strip()
    cases = []
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        date, issue, comp, action = cells[0], cells[1], cells[2], cells[3]
        # ข้ามหัวตาราง + เส้นคั่น
        if date in ("วันที่ซ่อม", "") or set(date) <= set("-:"):
            continue
        symptom = issue
        solution = action
        blob = f"เครื่อง {name} {issue} {comp} {action}"
        cases.append({
            "case_id":  f"{name}-{date}",
            "machine":  name,
            "symptom":  symptom,
            "solution": solution,
            "component": comp,
            "repair_date": date,
            "tags":     _derive_tags(blob),
            "_text":    blob,
        })
    return cases


def _parse_frontmatter(txt):
    """ดึง frontmatter (ระหว่าง --- คู่แรก) เป็น dict"""
    m = re.match(r"^---\s*\n(.*?)\n---", txt, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    return fm


def _parse_section(txt, header):
    """ดึงเนื้อใต้หัวข้อ '# header ...' จนเจอหัวข้อ # ถัดไป"""
    m = re.search(rf"^#\s*{re.escape(header)}[^\n]*\n(.*?)(?=\n#\s|\Z)", txt, re.S | re.M)
    return m.group(1).strip() if m else ""


# ขอบเขตเคสในไฟล์แบบหลายเคส: บรรทัด --- ที่ตามด้วย case_id: (frontmatter ของเคสถัดไป)
_CASE_SPLIT_RE = re.compile(r"(?=^---\s*\ncase_id:)", re.M)


def _parse_case_block(txt, fallback_id=""):
    """parse "1 block เคส" (frontmatter + หัวข้อ) -> case dict
    รับ string ของเคสเดียว — ใช้ได้ทั้งไฟล์เคสเดี่ยวเดิม และ block ที่ split จากไฟล์หลายเคส"""
    fm = _parse_frontmatter(txt)
    tags = [t.strip() for t in fm.get("tags", "").strip("[] ").split(",") if t.strip()]
    symptom  = _parse_section(txt, "อาการ")
    cause    = _parse_section(txt, "สาเหตุ")
    solution = _parse_section(txt, "วิธีแก้")
    result   = _parse_section(txt, "ผลลัพธ์")
    machine   = fm.get("machine", "?")
    component = fm.get("component", "")
    category  = fm.get("category", "")
    plant      = fm.get("plant", "")
    department = fm.get("department", "")
    try:
        downtime = int(re.sub(r"\D", "", fm.get("downtime_min", "0")) or 0)
    except Exception:
        downtime = 0
    # ข้อความที่ใช้ embed: เอาเฉพาะ "เนื้อจริง" ของเคส — ห้ามใส่คำ template
    # (เครื่อง/โรงงาน/ฝ่าย/หมวด/อาการ/สาเหตุ/วิธีแก้) เพราะคำพวกนี้ซ้ำทุกเคส
    # ทำให้ query ไทยอะไรก็ตาม (รวมคำทักทาย) คล้ายทุกเคสขึ้น -> พื้น cosine สูง แยก band ยาก
    blob = "\n".join(x for x in (
        f"{machine} {component}".strip(),
        f"{category} {' '.join(tags)}".strip(),
        symptom, cause, solution,
    ) if x and x.strip())
    return {
        "case_id":  fm.get("case_id") or fallback_id,
        "machine":  machine,
        "symptom":  symptom or "(ไม่ระบุอาการ)",
        "cause":    cause,
        "solution": solution or "(ไม่ระบุวิธีแก้)",
        "result":   result,
        "component": component or "-",
        "plant": plant,
        "department": department,
        "repair_date": fm.get("date", ""),
        "category": category,
        "severity": fm.get("severity", ""),
        "status":   fm.get("status", ""),
        "downtime_min": downtime,
        "tags":     tags or _derive_tags(blob),
        "_text":    blob,
    }


def _parse_case_file(path):
    """อ่านไฟล์ .md แล้วคืน list ของ case dict (รองรับทั้ง 1 ไฟล์ = 1 เคส และหลายเคส/ไฟล์)
    ระบุเคสจาก `case_id:` ใน frontmatter ของแต่ละ block — ไม่ผูกกับชื่อไฟล์
    ไฟล์ที่ไม่มี block case_id เลย (README, meetings, โน้ต) ได้ [] -> ไม่หลุดเข้า index"""
    txt = path.read_text(encoding="utf-8-sig")   # -sig กัน BOM ทำ frontmatter เคสแรก parse ไม่ติด
    cases = []
    for block in _CASE_SPLIT_RE.split(txt):
        fm = _parse_frontmatter(block)
        # เอาเฉพาะ block ที่ case_id มีค่าและขึ้นต้น MTN- (กรองแทนชื่อไฟล์ MTN-*.md เดิม
        # + กัน frontmatter ชนิดอื่นหลุดเข้ามา)
        if not fm.get("case_id", "").startswith("MTN-"):
            continue
        cases.append(_parse_case_block(block, fallback_id=path.stem))
    return cases


def load_cases():
    """อ่านเคสจาก cases/ (สเปก tag-first) — 1 ไฟล์มีได้หลายเคส แยกด้วย case_id ในเนื้อไฟล์"""
    if not VAULT_PATH:
        return []
    cdir = Path(VAULT_PATH) / "cases"
    if not cdir.exists():
        return []
    cases = []
    # rglob = อ่านลึกทุกชั้น cases/<plant>/<dept>/... (ไม่งั้นเคสในโฟลเดอร์ย่อยจะค้นไม่เจอ)
    for f in sorted(cdir.rglob("*.md")):
        try:
            cases.extend(_parse_case_file(f))
        except Exception:
            continue
    return cases


# ---------- embeddings (bge-m3 ผ่าน Ollama) ----------
def _normalize_base(url):
    url = (url or "").rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


_client = None


def _get_client():
    """OpenAI client ตัวเดียวใช้ซ้ำ — เปิด connection ค้างไว้
    (สร้างใหม่ทุก call บน Windows ช้า ~2s เพราะ localhost ลอง IPv6 ก่อน timeout)"""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=_normalize_base(QWEN_BASE_URL), api_key=QWEN_API_KEY)
    return _client


_azure_client = None


def _get_azure_client():
    """AzureOpenAI client สำหรับโมเดล API คลาวด์ (gpt-5.4-mini ฯลฯ)
    ใช้ azure_endpoint + api_key + api_version จาก .env"""
    global _azure_client
    if _azure_client is None:
        from openai import AzureOpenAI
        _azure_client = AzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=AZURE_API_KEY,
            api_version=AZURE_API_VER,
        )
    return _azure_client


def _is_azure_model(model_id):
    """ตรวจว่า model ที่เลือกเป็น Azure API model หรือไม่ (prefix azure:)"""
    return (model_id or "").strip().startswith("azure:")


def _is_n8n_model(model_id):
    """ตรวจว่า model ที่เลือกวิ่งผ่าน n8n proxy หรือไม่ (prefix n8n)"""
    return (model_id or "").strip().startswith("n8n")


def _n8n_ask(context, question):
    """ยิงคำถาม+context ไป webhook n8n -> คืนข้อความคำตอบ (n8n forward ให้ Azure เอง)
    n8n Code node คืน {text}; เผื่อ n8n ห่อเป็น array ก็ยังอ่านได้"""
    import requests
    resp = requests.post(N8N_ASK_URL, json={"context": context, "question": question}, timeout=90)
    resp.raise_for_status()
    body = (resp.text or "").strip()
    # n8n คืน 200 body ว่าง = node "Respond to Webhook" ยัง disabled -> บอกชัดแทนคืนค่าว่างเงียบ
    if not body:
        raise RuntimeError("n8n คืน body ว่าง — เปิด node 'Respond to Webhook' ใน workflow ask_javis")
    data = resp.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return (data.get("text") or "").strip()


def _azure_deployment(model_id):
    """ดึงชื่อ deployment จาก model_id (azure:gpt-5.4-mini -> AZURE_DEPLOYMENT)
    หรือถ้ามี custom deployment name หลัง prefix ก็ใช้ตามนั้น"""
    name = (model_id or "").strip().removeprefix("azure:").strip()
    return name or AZURE_DEPLOYMENT


def _embed(texts):
    """คืน list ของเวกเตอร์ (list[float]); โยน exception ถ้าต่อไม่ติด"""
    resp = _get_client().embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# cache เวกเตอร์ของเคสไว้ในหน่วยความจำ (กัน embed ซ้ำทุก request)
_CACHE = {"key": None, "cases": None, "vecs": None}


def _ensure_index():
    """โหลดเคส + embed (ใช้ cache ถ้าเนื้อไม่เปลี่ยน). คืน (cases, vecs) หรือ (None,None)"""
    cases = load_cases()
    if not cases:
        return None, None
    key = tuple(c["case_id"] + c["_text"] for c in cases)
    if _CACHE["key"] == key:
        return _CACHE["cases"], _CACHE["vecs"]
    vecs = _embed([c["_text"] for c in cases])
    _CACHE.update(key=key, cases=cases, vecs=vecs)
    return cases, vecs


# ---------- API ที่ app.py เรียก ----------
def get_case(case_id):
    """หาเคสเดียวตาม case_id (ไม่สนตัวพิมพ์เล็ก/ใหญ่) — ให้หน้าเว็บกดดูจาก citation
    คืน dict (ตัดคีย์ภายใน _*) หรือ None ถ้าไม่พบ"""
    cid = (case_id or "").strip().casefold()
    if not cid:
        return None
    for c in load_cases():
        if c["case_id"].casefold() == cid:
            return {k: v for k, v in c.items() if not k.startswith("_")}
    return None


def all_plants():
    """รายชื่อโรงงานที่มีเคสจริง (ไว้ทำ dropdown กรอง) — ไม่รวมค่าว่าง/_unsorted"""
    plants = set()
    for c in load_cases():
        p = (c.get("plant") or "").strip()
        if p and p != "_unsorted":
            plants.add(p)
    return sorted(plants)


def all_departments():
    """รายชื่อฝ่ายที่เคยใช้ (ไว้ทำ datalist แนะนำในฟอร์ม) — กันพิมพ์ชื่อฝ่ายซ้ำ/เพี้ยน"""
    depts = set()
    for c in load_cases():
        d = (c.get("department") or "").strip()
        if d and d != "_unsorted":
            depts.add(d)
    return sorted(depts)


def search(query, k=8, plant=None):
    """ค้นเคสด้วย semantic similarity. คืน list[case] (มี score%) หรือ None ถ้าทำไม่ได้
    plant: ถ้าระบุ -> กรองเฉพาะเคสของโรงงานนั้น (isolation ไม่ให้ดึงข้ามโรงงาน)
           คืน [] (ไม่ใช่ None) ถ้าโรงงานนั้นยังไม่มีเคส -> จะไม่ตกไปโรงอื่น/mock"""
    try:
        cases, vecs = _ensure_index()
        if not cases:
            return None
        if plant:
            pf = plant.strip().casefold()
            keep = [(c, v) for c, v in zip(cases, vecs)
                    if (c.get("plant") or "").strip().casefold() == pf]
            if not keep:
                return []
            cases = [c for c, _ in keep]
            vecs = [v for _, v in keep]
        qv = _embed([query])[0]
        scored = []
        for c, v in zip(cases, vecs):
            sim = _cosine(qv, v)
            c2 = {kk: vv for kk, vv in c.items() if not kk.startswith("_")}
            c2["score"] = max(0, round(sim * 100))
            scored.append((sim, c2))
        scored.sort(key=lambda x: -x[0])
        # กรองผลใกล้เคียงจอมปลอม: พิมพ์มั่ว/นอกโดเมน bge-m3 ยังคืนเพื่อนบ้านใกล้สุด ~25% อยู่ดี
        # -> ตัดด้วย floor เฉพาะ search (รู้จักคำพิมพ์ไม่จบ) คำถามมั่วจะเหลือ []
        floor = _search_floor(query)
        return [c for _, c in scored[:k] if c["score"] >= floor]
    except Exception as e:
        print(f"[RAG] search ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ตก mock")
        return None


# คำช่างพื้นฐาน (นอกเหนือจากคีย์เวิร์ดใน _TAG_RULES) — บ่งว่าเป็นคำถามซ่อมบำรุง
_DOMAIN_EXTRA = ["เครื่อง", "ซ่อม", "เสีย", "พัง", "อะไหล่", "เปลี่ยน", "สั่น", "เสียงดัง",
                 "หยุดเดิน", "ทริป", "อุณหภูมิ", "หยด", "ตัน", "สึก", "ขาด", "หลวม", "คาลิเบรต"]


def _domain_vocab():
    """คลังศัพท์ช่างไว้เช็คว่าคำถาม in-domain ไหม: คีย์เวิร์ด tag + คำช่างพื้นฐาน
    + ชื่อเครื่อง/อะไหล่/tag จริงจาก vault (คำ >=3 ตัวอักษร). cache ใน _CACHE ตาม index"""
    if _CACHE.get("vocab") is not None:
        return _CACHE["vocab"]
    vocab = {kw for _, kws in _TAG_RULES for kw in kws} | set(_DOMAIN_EXTRA)
    for c in load_cases():
        for field in (c.get("machine", ""), c.get("component", "")):
            vocab.update(w.casefold() for w in re.split(r"[\s\-_/]+", field) if len(w) >= 3)
        vocab.update(t.casefold() for t in c.get("tags", []) if len(t) >= 3)
    vocab = {w for w in vocab if w and w not in ("?",)}
    _CACHE["vocab"] = vocab
    return vocab


def _rel_min_for(query):
    """เลือกเกณฑ์ตามว่าคำถามมีศัพท์ช่างไหม (string match ล้วน — 0ms)"""
    q = query.casefold()
    return REL_MIN_DOMAIN if any(w in q for w in _domain_vocab()) else REL_MIN_OTHER


def _search_floor(query):
    """เกณฑ์ score หน้าค้นเคส — รู้จัก "พิมพ์ไม่จบ" ด้วย (เช่น "มอเตอ" = ต้นคำ "มอเตอร์")
    in-domain: เจอศัพท์ช่างในคำถาม หรือคำถาม(>=2)เป็นส่วนต้นของศัพท์ช่าง -> เกณฑ์ผ่อน
    ไม่งั้น (มั่ว/นอกโดเมน) -> เกณฑ์สูงกว่า กันเพื่อนบ้านจอมปลอม"""
    q = query.casefold().strip()
    vocab = _domain_vocab()
    hit = any(w in q for w in vocab)
    if not hit and len(q) >= 2:
        hit = any(q in w for w in vocab)   # พิมพ์ค้าง -> match ต้นคำศัพท์ช่าง
    return SEARCH_MIN_DOMAIN if hit else SEARCH_MIN_OTHER


# คำถามเชิงวิเคราะห์ (นับ/สรุป/ภาพรวม) — คำตอบอยู่ที่การมองเคส "ทั้งกอง" ไม่ใช่จับคู่รายเคส
# reranker ใช้กับพันธุ์นี้ไม่ได้ (ถามรายเคสว่า "ตอบคำถามนี้ได้ไหม" ทุกเคสจะตอบว่าไม่ได้ -> ตัดหมด)
_AGG_RE = re.compile(r"กี่(เคส|ครั้ง|เรื่อง|อัน|เครื่อง)|ทั้งหมด|อะไรบ้าง|มีเคส|สรุป|"
                     r"(บ่อย|มาก|น้อย|นาน|สูง|ต่ำ|เยอะ)(ที่)?สุด|"
                     r"เท่าไหร่|เท่าไร|จำนวน|แนวโน้ม|เปรียบเทียบ|เรียงตาม|"
                     r"เล่ามา|ลิสต์|รายการ|ทั้งหมดกี่|มีบ้าง|"
                     r"(เครื่องไหน|เคสไหน|ตัวไหน|อันไหน)[^?]*บ้าง|"   # "เครื่องไหน...บ้าง" = ขอ list -> วิเคราะห์
                     r"\bwhich machines\b|\bwhich cases\b|"           # อังกฤษพหูพจน์ = list
                     r"\bhow many\b|\bhow much\b|\bmost\b|\bleast\b|\blongest\b|"
                     r"\bhighest\b|\blowest\b|\btotal\b|\baverage\b", re.I)

# สัญญาณ "อาจเป็นคำถามวิเคราะห์" (หลวมกว่า _AGG_RE) — ด่านคัดก่อนเรียก LLM ตัดสินเลน
# ไม่มีสัญญาณพวกนี้เลย = คำถามวิธีแก้ตรงๆ -> ข้าม classify ไม่เปลืองเวลา/เงินเรียก LLM
_MAYBE_AGG_RE = re.compile(
    r"สุด|มากกว่า|น้อยกว่า|เคสไหน|อันไหน|ตัวไหน|เครื่องไหน|กี่|จำนวน|เฉลี่ย|รวม|อันดับ|"
    r"downtime|severity|เสียเวลา|ซ่อมนาน|หยุดนาน|"
    r"\bwhich\b|\bhow many\b|\bhow much\b|\bmost\b|\bleast\b|\blongest\b|\bhighest\b|"
    r"\blowest\b|\btotal\b|\baverage\b|\brank\b|\btop\b|\blist\b|\ball cases\b|\bcompare\b",
    re.I)


def _case_ctx(cases):
    """แปลงรายการเคสเป็น context บรรทัดละเคส (เลนปกติ — เน้นวิธีแก้ ไม่มีตัวเลขสถิติ)"""
    return "\n".join(
        f"[{c['case_id']}] โรงงาน: {c.get('plant') or '-'} ฝ่าย: {c.get('department') or '-'} "
        f"เครื่อง {c['machine']} อาการ: {c['symptom']} "
        f"จุด: {c['component']} วิธีแก้: {c['solution']}"
        for c in cases
    )


def _analytic_ctx(cases):
    """context เลนวิเคราะห์ — ใส่ severity/downtime/วันที่ ให้ LLM นับ/จัดอันดับได้จริง
    (เลนปกติไม่แตะ context นี้ -> คำถามวิธีแก้เดิมไม่กระทบ + ตาข่าย groundedness ไม่เพี้ยน)"""
    return "\n".join(
        f"[{c['case_id']}] โรงงาน:{c.get('plant') or '-'} ฝ่าย:{c.get('department') or '-'} "
        f"เครื่อง:{c['machine']} severity:{c.get('severity') or '-'} "
        f"downtime:{c.get('downtime_min', 0)}นาที วันที่:{c.get('repair_date') or '-'} "
        f"อาการ:{c['symptom']} สาเหตุ:{c.get('cause') or '-'} "
        # ใส่ tags + สาเหตุ ให้ GPT จำแนกหัวข้อได้ถูก — อาการอย่างเดียวไม่พอ
        # (เช่น Pump P-07 อาการ "เสียงดังสั่น" ไม่มีคำ bearing แต่ tag/สาเหตุบอกว่าเป็น bearing)
        f"tags:{','.join(c.get('tags') or []) or '-'}"
        for c in cases
    )


def _llm_chat(messages, use_model, stop=None, n8n_context=None, n8n_question=None):
    """เรียก LLM ตาม routing: n8n* -> webhook n8n, azure:* -> Azure OpenAI, อื่น -> Ollama local
    คืนข้อความคำตอบ. เลน n8n ใช้ n8n_context/n8n_question (n8n ประกอบ prompt + ถือ key เอง)"""
    from llm import QWEN_MODEL
    if _is_n8n_model(use_model):
        if not N8N_READY:
            raise RuntimeError("N8N_ASK_URL ยังไม่ได้ตั้งค่าใน .env")
        return _n8n_ask(n8n_context or "", n8n_question or "")
    if _is_azure_model(use_model):
        if not AZURE_READY:
            raise RuntimeError("Azure OpenAI ยังไม่ได้ตั้งค่าใน .env")
        # หมายเหตุ: gpt-5.4-mini (Azure) ไม่รองรับ stop param — พึ่ง system prompt อย่างเดียว (ก็พอ)
        resp = _get_azure_client().chat.completions.create(
            model=_azure_deployment(use_model), messages=messages, temperature=0.2)
    else:
        # local (Ollama) รองรับ stop — ตัดทันทีถ้าเผลอลอกหัว context/โครง prompt
        kw = {"stop": stop} if stop else {}
        resp = _get_client().chat.completions.create(
            model=use_model or QWEN_MODEL, messages=messages, temperature=0.2, **kw)
    return resp.choices[0].message.content.strip()


def _classify_lane(query, use_model):
    """เมื่อ regex ไม่ชัด -> ให้ LLM ตัดสินว่าเข้าเลนไหน. คืน 'analytic' | 'case'
    graceful degradation: LLM ล่ม/ตอบแปลก -> 'case' (เลนปกติ ปลอดภัยสุด ไม่พังทั้งระบบ)"""
    try:
        out = _llm_chat(
            [{"role": "system", "content":
              "คุณคือ router จำแนกคำถามช่างซ่อมบำรุง ตอบคำเดียวเท่านั้น: analytic หรือ case\n"
              "analytic = ถามภาพรวม/นับ/จัดอันดับ/เปรียบเทียบหลายเคส "
              "(เช่น เคสไหน downtime มากสุด, มีกี่เคส, severity สูงมีอะไรบ้าง, show most downtime)\n"
              "case = ถามวิธีแก้/อาการ/สาเหตุ ของปัญหาเรื่องเดียว "
              "(เช่น ปั๊มสั่นแก้ยังไง, มอเตอร์ไหม้เพราะอะไร, how to fix bearing)"},
             {"role": "user", "content": query}],
            use_model)
        return "analytic" if "analytic" in (out or "").lower() else "case"
    except Exception:
        return "case"


def _analytic_answer(query, plant, use_model, used):
    """เลนคำถามวิเคราะห์ (นับ/สรุป/ภาพรวม): กรองเคสตามฝ่าย/โรงงานที่ถูกเอ่ยในคำถาม
    แล้วส่งทั้งชุดให้ LLM มองรวม — ข้าม reranker/ตาข่าย groundedness ที่ออกแบบมาสำหรับจับคู่รายเคส"""
    cases = load_cases()
    if not cases:
        return None
    if plant:
        pf = plant.strip().casefold()
        cases = [c for c in cases if (c.get("plant") or "").strip().casefold() == pf]

    # ชื่อถูก "เอ่ยถึง" = เจอทั้งคำ ไม่ใช่แค่ substring — กันชื่อสั้นชน (โรงงาน 'B' ไปชนคำว่า 'CB')
    def _mentioned(name, cue_re=None):
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", query, re.I):
            return False
        # ชื่อกำกวม (คำทั่วไป / ตัวอักษรเดียว) ต้องมีคำนำหน้า (ฝ่าย/โรงงาน/dept/plant) ถึงนับเป็นตัวกรอง
        # กัน "high-severity maintenance cases" -> ฝ่าย Maintenance (เหลือเคสเดียว)
        # และ "replace it with a new motor" -> โรงงาน A (ตัว 'a' article ชนชื่อโรงงาน)
        if cue_re is not None and (len(name.strip()) <= 1 or name.strip().casefold() in _AMBIGUOUS_NAMES):
            return bool(cue_re.search(query))
        return True

    # จำกัดขอบเขตตามฝ่าย/โรงงานที่พูดถึงในคำถาม (string match ตรงๆ — deterministic)
    depts = {d.casefold() for d in all_departments() if _mentioned(d, _DEPT_CUE_RE)}
    if depts:
        cases = [c for c in cases if (c.get("department") or "").casefold() in depts]
    plants = {p.casefold() for p in all_plants() if _mentioned(p, _PLANT_CUE_RE)}
    if plants:
        cases = [c for c in cases if (c.get("plant") or "").casefold() in plants]
    # กรองตาม 'หัวข้อ' ที่ถาม (bearing/motor/pump...) — deterministic ป้อน GPT เฉพาะเคสที่มีของจริง
    # (กันมโน: "เครื่องไหนมีปัญหา bearing" -> เหลือเฉพาะเคส bearing จริง ไม่ให้ GPT เดาจากเคสทั้งกอง)
    topics = _query_topics(query)
    if topics:
        cases = [c for c in cases if _case_matches_topics(c, topics)]
    # กรองตามเงื่อนไข metric (severity / downtime เกิน N) ใน Python — ไม่ให้ LLM หาเอง
    # LLM เคยตอบไม่ครบ (ถาม high-severity 13 เคส ตอบ 1) เพราะต้อง "หา" เองจากกองเคส
    # กรองก่อน = subset คือคำตอบอยู่แล้ว -> enumerate ครบเสมอ + scale (ไม่ป้อนพันเคสเข้า LLM)
    # กันพัง: กรองแล้วไม่เหลือเคส -> คงชุดเดิมไว้ (พฤติกรรมเดิม) ไม่ตอบว่างมั่ว
    filters = _parse_filters(query)
    prefiltered = False
    if filters:
        matched = [c for c in cases if _match_filters(c, filters)]
        if matched:
            cases = matched
            prefiltered = True
    where = f"โรงงาน {plant}" if plant else "ระบบ"
    en = _is_english(query)   # ถามอังกฤษ -> ตอบอังกฤษ (เลนวิเคราะห์รองรับ 2 ภาษาเหมือนเลนปกติ)
    if not cases:
        return {"text": ("No relevant case found." if en else f"ไม่พบเคสที่เกี่ยวข้องใน{where}"),
                "citations": [], "model": used}
    total = len(cases)                       # จำนวนจริงก่อนตัด — ใช้ตอบคำถามเชิงนับ
    # ตัดกัน context บวม แต่ต้องใหญ่พอให้ aggregate (นับ/downtime/severity) เห็นเคสครบ
    # ค่าเก่า 25 ทำให้ downtime>60 ตกหล่นเคสที่ 26+ (vault มี 31) -> ตอบผิด
    # vault โตมากในอนาคต: กรอง deterministic ใน Python ก่อน (ดู topic filter ด้านบน) ให้ subset เล็กพอ
    cases = cases[:_ANALYTIC_MAX]
    lang_line = ("Respond ENTIRELY in English. The case data is Thai — translate values into English. "
                 if en else "ตอบเป็นภาษาไทย ")
    system_msg = (
        lang_line +
        "คุณคือผู้ช่วยช่างซ่อมบำรุง วิเคราะห์จากรายการเคสที่ให้มาเท่านั้น (นับ/สรุป/จัดอันดับตามจริง) "
        "downtime = นาทีที่เครื่องหยุด (ค่ามาก = นานสุด) severity = ระดับความรุนแรง high/medium/low. "
        "ถ้าคำถามขอ 'รายการ/เครื่องไหนบ้าง/list/show/which' -> ระบุให้ครบทุกเคสที่เข้าเงื่อนไข "
        "ห้ามสรุปเหลือแค่ตัวเด่น (เช่น ถาม downtime>60 ต้องลิสต์ทุกเคสที่เกิน ไม่ใช่เฉพาะนานสุด). "
        "ตอบสั้นเป็นประโยคสรุปของคุณเอง ห้ามเดา/เพิ่มความรู้ทั่วไป "
        "ห้ามลอกบรรทัดข้อมูลดิบ ห้ามพิมพ์ field ดิบเช่น 'ฝ่าย:' 'อาการ:' 'downtime:' "
        "หรือรหัสเคสในวงเล็บเหลี่ยม '[MTN-...]' — อ้างชื่อเคสแบบ MTN-xxxx ได้ (ไม่มีวงเล็บเหลี่ยม) "
        "ใช้เฉพาะชื่อเครื่อง/รหัสเคสที่ปรากฏในรายการเท่านั้น ห้ามแต่งชื่อเครื่องหรือรหัสขึ้นเอง "
        "รูปแบบอ้างอิง: <ชื่อเครื่องจากรายการ> (เคส <case_id จากรายการ>)"
    )
    # ถ้ารายการถูกตัด (เกิน 25) ต้องบอกจำนวนจริงในหัวรายการ — ไม่งั้นโมเดลนับได้แค่ที่เห็น
    head = f"รายการเคส (ทั้งหมด {total} เคส แสดง {len(cases)} เคสแรก):" if total > len(cases) \
           else "รายการเคส:"
    ctx_block = f"{head}\n{_analytic_ctx(cases)}"   # <- context มี downtime/severity (ต่างจากเลนปกติ)
    user_msg = f"{ctx_block}\n\nคำถาม: {query}"
    # กรอง deterministic มาแล้ว -> บอกโมเดลว่าห้ามคัดออกเอง (มันชอบกรองซ้ำจากคำในคำถาม
    # เช่น "maintenance cases" -> ไปจับ ฝ่าย:Maintenance ใน context แล้วตอบเคสเดียว)
    if prefiltered:
        cond = ", ".join((f"severity={v}" if k == "severity" else f"downtime > {v} นาที")
                         for k, v in filters.items())
        user_msg += (f"\n\nหมายเหตุ: รายการข้างบนถูกกรองมาแล้วว่าเข้าเงื่อนไข ({cond}) ครบทุกเคส "
                     f"— ต้องระบุให้ครบทั้ง {len(cases)} เคส ห้ามคัดออกเอง ห้ามกรองซ้ำจากคำอื่นในคำถาม")
    user_msg += ("\n\nIMPORTANT: Write your ENTIRE answer in English only."
                 if en else "\n\nสำคัญ: ตอบเป็นภาษาไทยทั้งหมด")
    text = _llm_chat([{"role": "system", "content": system_msg},
                      {"role": "user", "content": user_msg}],
                     use_model, stop=["รายการเคส:", "รายการเคส (", "คำถาม:"],
                     n8n_context=ctx_block, n8n_question=query)
    # ตาข่ายกันดิบ (เลนวิเคราะห์): โมเดลตัวเล็กชอบลอก context ทั้งบรรทัด (เจอ [MTN-]/ฝ่าย:)
    # -> แทนด้วยสรุปนับ + รายการเครื่องที่ปลอดภัย (ไม่มีรหัสเคส/ข้อมูลหลังบ้าน)
    if len(text) < 4 or _looks_like_dump(text):
        machines = list(dict.fromkeys(c.get("machine", "").strip() for c in cases if c.get("machine")))
        text = ((f"Found {total} cases: " if en else f"พบ {total} เคสใน{where}: ")
                + ", ".join(machines[:10]))
    # บังคับภาษาให้ตรง (GPT บางทีดื้อ ถามอังกฤษตอบไทย) -> คำตอบผิดภาษา แปลซ้ำ 1 ครั้ง
    # ผิดภาษา = ภาษาคำถามกับภาษาคำตอบ "ตรงกัน" ในเชิงบูลีน (en=True คู่กับ ตอบไทย=True)
    if text and (en == _is_thai_answer(text)):
        try:
            tr = _llm_chat([{"role": "system", "content":
                             f"Translate to {'English' if en else 'Thai'}. Output ONLY the translation, "
                             "same meaning, concise. Keep case codes/numbers as-is."},
                            {"role": "user", "content": text}], use_model)
            if tr and len(tr.strip()) > 3:
                text = tr.strip()
        except Exception:
            pass
    # citation ตรงกับคำตอบ: อ้างเฉพาะเคสที่ 'ชื่อเครื่อง' โผล่ในคำตอบจริง (ที่ GPT หยิบมาพูด)
    # คำตอบเชิงนับ/สรุปที่ไม่เอ่ยชื่อเครื่อง (เช่น "พบ 5 เคส") -> ตกมาอ้างเคสที่ตรงหัวข้อทั้งชุด
    low = (text or "").casefold()
    # match ด้วย case_id (GPT พิมพ์ "(เคส MTN-xxxx)" เสมอ — แม่นสุด แม้ชื่อเครื่องถูกแปล/ย่อ)
    # เสริมด้วยชื่อเครื่อง เผื่อคำตอบเอ่ยชื่อแต่ไม่ใส่รหัส
    named = [c for c in cases if c["case_id"].casefold() in low
             or ((c.get("machine") or "").strip() and c["machine"].strip().casefold() in low)]
    cited = named or cases
    return {"text": text, "citations": [c["case_id"] for c in cited[:20]], "model": used}


def answer(query, k=4, plant=None, model=None):
    """RAG: ดึงเคสที่เกี่ยว -> LLM สรุป. คืน {text, citations} หรือ None
    plant: จำกัดขอบเขตให้ตอบจากเคสในโรงงานนั้นเท่านั้น
    model: ชื่อโมเดลที่ผู้ใช้เลือกหน้าเว็บ (ว่าง/None = ใช้ default_model())"""
    # โมเดลที่ผู้ใช้เลือก (azure:* = คลาวด์, อื่น/ว่าง = local ตาม .env) — ใช้ echo กลับทุกเส้นทาง
    use_model = (model or "").strip() or default_model()
    used = use_model
    try:
        # เลนวิเคราะห์: คำถามนับ/สรุป/ภาพรวม/จัดอันดับ — ต้องเห็นเคสทั้งกอง reranker รายเคสจะตัดหมด
        # hybrid routing: regex คำชัด -> เข้าเลย (เร็ว/ฟรี) ; regex ไม่ชัดแต่มีสัญญาณ -> LLM ตัดสิน
        # (ไม่มีสัญญาณเลย = ถามวิธีแก้ตรงๆ -> ข้าม classify ไม่เสียเวลาเรียก LLM)
        if _AGG_RE.search(query) or \
           (_MAYBE_AGG_RE.search(query) and _classify_lane(query, use_model) == "analytic"):
            return _analytic_answer(query, plant, use_model, used)
        # ดึงกว้างกว่า k (คัดหยาบ) — reranker จะเป็นคนคัดละเอียดทีหลัง
        hits = search(query, k=max(k * 2, 10), plant=plant)
        if hits is None:
            return None                     # vault ว่าง/backend มีปัญหา -> ให้ app ตก mock
        where = f"โรงงาน {plant}" if plant else "ระบบ"
        en = _is_english(query)   # คำถามอังกฤษ -> ตอบ/ข้อความปฏิเสธเป็นอังกฤษ
        not_found = f"No relevant case found in the {plant} plant." if (en and plant) else \
                    "No relevant case found." if en else f"ไม่พบเคสที่เกี่ยวข้องใน{where}"
        # ชั้นคัดละเอียด: cross-encoder อ่านคำถาม+เคสคู่กัน -> เกี่ยวจริงไหม (คมกว่าคะแนน embed มาก)
        # ข้ามเฉพาะคำถามอังกฤษ: reranker (mmarco) จับ English query ↔ Thai case ไม่ได้ ให้คะแนนมั่ว
        # กดเคสที่ตรงจริงตก (เช่น "motor overload" -> เคสมอเตอร์ไหม้ได้ 0.02) -> ใช้ embed bge-m3 แทน
        # (bge-m3 multilingual จัดอันดับข้ามภาษาได้ดีอยู่แล้ว) ; ไทยยังใช้ reranker เต็มเหมือนเดิม
        rr_scores = None if en else _rerank(query, hits)
        if rr_scores is not None:
            rel_hits = [h for h, s in zip(hits, rr_scores) if s >= RERANK_MIN][:k]
            if not rel_hits:
                # reranker ตัดหมด -> ลอง keyword lookup (คำเดี่ยว/STT เพี้ยน ที่ reranker ให้คะแนนต่ำ)
                rel_hits = _lexical_hits(query, hits)[:k]
            if not rel_hits:
                # ไม่เกี่ยวทั้งความหมายและคีย์เวิร์ด -> ปฏิเสธ ไม่แนบ citation ไม่เรียก LLM
                return {"text": not_found, "citations": [], "model": used}
        else:
            # reranker ใช้ไม่ได้ -> gate แบบเดิม: เกณฑ์คะแนน embed + margin จากตัวท็อป
            rel_min = _rel_min_for(query)
            hits = [h for h in hits if h.get("score", 0) >= rel_min][:k]
            if not hits:
                return {"text": not_found, "citations": [], "model": used}
            top = hits[0].get("score", 0)
            rel_hits = [h for h in hits if h.get("score", 0) >= top - _FALLBACK_MARGIN]
        ctx = _case_ctx(rel_hits)
        # prompt แยก system (กฎ) / user (ข้อมูล+คำถาม) — กันโมเดลตัวเล็กลอก context/โครง prompt ซ้ำ
        # (เลิกใช้ก้อนเดียวจบด้วย "คำตอบ:" ที่ทำให้ Typhoon พ่นข้อมูลดิบกลับมา)
        # ตรวจภาษาคำถามใน Python (ไม่พึ่งให้โมเดลเดา) แล้วบังคับ directive ให้ชัด
        lang_line = ("Respond ENTIRELY in English. The case data below is Thai — translate/summarize it into English. "
                     if en else "ตอบเป็นภาษาไทยทั้งหมด แม้คำถามจะมีคำภาษาอังกฤษปนอยู่ก็ตอบเป็นภาษาไทย ")
        system_msg = (
            lang_line +
            "คุณคือผู้ช่วยช่างซ่อมบำรุง ตอบสั้นกระชับ ใช้เฉพาะข้อมูลจากเคสที่ให้มา "
            "ห้ามลอกรหัสเคส (เช่น MTN-xxxx) ชื่อฝ่าย หรือข้อความเคสดิบออกมา ให้ย่อยเป็นคำแนะนำวิธีแก้เท่านั้น "
            "แต่ละเคสระบุโรงงาน/ฝ่ายไว้ ถ้าคำถามเจาะจงโรงงานใด ให้ตอบเฉพาะเคสของโรงงานนั้น "
            "สรุปวิธีแก้จากเคสที่ตรงกับคำถาม ห้ามเพิ่มความรู้ทั่วไปนอกเหนือจากเคส "
            "เฉพาะกรณีที่ไม่มีเคสไหนเกี่ยวกับคำถามเลย จึงตอบว่าไม่พบเคสที่ตรง"
        )
        user_msg = f"เคสที่เกี่ยวข้อง:\n{ctx}\n\nคำถาม: {query}"
        user_msg += ("\n\nIMPORTANT: Write your ENTIRE answer in English only." if en
                     else "\n\nสำคัญ: ตอบเป็นภาษาไทยทั้งหมดเท่านั้น")
        messages = [{"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}]
        text = _llm_chat(messages, use_model, stop=["เคสที่เกี่ยวข้อง:", "คำถาม:"],
                         n8n_context=ctx, n8n_question=query)
        # ตาข่ายกันขยะ: ถ้าโมเดล (ตัวเล็ก) ยังเผลอลอกข้อมูลเคสดิบ (เจอ marker) หรือ stop ตัดจนเหลือว่าง
        # -> ทิ้งแล้วสรุปวิธีแก้จากเคสเกี่ยวจริงเอง (deterministic) ไม่ให้เห็นข้อมูลหลังบ้าน/คำตอบว่าง
        if len(text) < 8 or _looks_like_dump(text):
            sols = list(dict.fromkeys(h.get("solution", "").strip() for h in rel_hits if h.get("solution")))
            text = (("Suggested fix from similar cases: " if en else "แนวทางแก้จากเคสใกล้เคียง: ") + " • ".join(sols[:3])) if sols else ("No matching case." if en else "ไม่พบเคสที่ตรง")
        # ตาข่ายกันมโน: คำตอบแนะนำที่เนื้อไม่ตรงกับเคสเลย = โมเดลหยิบความรู้ทั่วไปมาตอบ (hallucination)
        # -> แทนด้วยวิธีแก้จริงจากเคส (คำตอบปฏิเสธ "ไม่พบ..." ไม่ต้องเช็ค — สั้นและไม่อิงเคสโดยธรรมชาติ)
        # อังกฤษก็เข้าตาข่ายนี้ด้วย: _grounded_score แปลคำตอบกลับไทยก่อนวัดกับ ctx ไทย
        elif not _is_reject(text, en) and _grounded_score(text, ctx, en, use_model) < GROUND_MIN:
            sols = list(dict.fromkeys(h.get("solution", "").strip() for h in rel_hits if h.get("solution")))
            text = (("Suggested fix from similar cases: " if en else "แนวทางแก้จากเคสใกล้เคียง: ") + " • ".join(sols[:3])) if sols else ("No matching case." if en else "ไม่พบเคสที่ตรง")
        # บังคับภาษาให้ตรง: GPT บางทีดื้อ (ถามไทยมีอังกฤษปน -> ตอบอังกฤษ) ไม่ฟัง prompt
        # -> เช็คภาษาคำตอบจริง ถ้าไม่ตรง แปลซ้ำ 1 ครั้ง (deterministic ไม่พึ่งโมเดลเชื่อฟัง)
        if text and (en == _is_thai_answer(text)):
            tgt = "English" if en else "Thai"
            try:
                tr = _llm_chat(
                    [{"role": "system", "content": f"Translate the text to {tgt}. Output ONLY the translation, "
                                                   "same meaning, concise. Keep codes/numbers (e.g. V-203) as-is."},
                     {"role": "user", "content": text}], use_model)
                if tr and len(tr.strip()) > 3:
                    text = tr.strip()
            except Exception:
                pass
        # citation: ตัดทิ้งเฉพาะตอน "ปฏิเสธล้วน" (มีคำว่าไม่พบ + ไม่มีคำแนะนำเลย)
        # ถ้าคำตอบมีคำแนะนำจริง (วิธีแก้/ควร/ตรวจ...) ต่อให้ขึ้นต้นว่า "ไม่พบเคสตรง" ก็ยังอ้างเคส
        # อ้างเคสเดียวที่ 'คำตอบใช้จริง' (ชื่อเครื่องตรง/เนื้อทับมากสุด) ไม่ใช่ rel_hits[0] ดื้อๆ
        is_pure_reject = bool(_STRONG_REJECT_RE.search(text)) or \
                         bool(_NOT_FOUND_RE.search(text) and not _ADVICE_RE.search(text)) or \
                         (en and bool(_EN_NOT_FOUND_RE.search(text)))
        cite = _best_citation(text, rel_hits, en, use_model)
        citations = [] if (is_pure_reject or not cite) else [cite["case_id"]]
        return {"text": text, "citations": citations, "model": used}
    except Exception as e:
        print(f"[RAG] answer ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ตก mock")
        return None


def stats():
    """สรุปตัวเลข dashboard จากเคสจริงใน vault. คืน (stats, categories) หรือ None"""
    cases = load_cases()
    if not cases:
        return None
    machines = {c["machine"] for c in cases}
    downtime = sum(c.get("downtime_min", 0) for c in cases)
    facet = {}
    for c in cases:
        # จัดกลุ่มด้วย category (สเปก) ถ้ามี ไม่งั้นใช้ tags
        keys = [c["category"]] if c.get("category") else c.get("tags", [])
        for k in keys:
            facet[k] = facet.get(k, 0) + 1
    categories = [{"name": t, "count": n}
                  for t, n in sorted(facet.items(), key=lambda x: -x[1])]
    st = {"total": len(cases), "downtime": downtime, "machines": len(machines)}
    return st, categories


def _parse_date(s):
    """แปลงวันที่จากเคส/ฟิลเตอร์เป็น date object (best-effort)
    รองรับ 2026-06-10 / 10/06/2026 / 10-06-69 / '10 มิ.ย. 2569' (พ.ศ.).
    อ่านไม่ออก -> None (ฝั่งกรองจะไม่ตัดเคสนั้นทิ้ง)"""
    from datetime import date
    s = (s or "").strip()
    if not s:
        return None
    nums = re.findall(r"\d+", s)
    try:
        if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", s):   # ISO: ปีมาก่อน
            y, m, d = int(nums[0]), int(nums[1]), int(nums[2])
        elif len(nums) >= 3:                                # วัน/เดือน/ปี
            d, m, y = int(nums[0]), int(nums[1]), int(nums[2])
        else:
            return None
        if y > 2400:            # พ.ศ. -> ค.ศ.
            y -= 543
        elif y < 100:           # ปี 2 หลัก -> 20xx
            y += 2000
        return date(y, m, d)
    except Exception:
        return None


def bubbles(plant=None, date_from=None, date_to=None):
    """ข้อมูลหน้า bubble dashboard: เคสจริงจัดกลุ่มตาม category (fallback tag แรก)
    แต่ละฟอง = 1 เคส (symptom) พร้อม cause/solution ให้ panel + jarvis ใช้ต่อ
    กรองตามโรงงาน + ช่วงวันที่ซ่อม (อ่านวันที่ไม่ออก = ไม่ตัดทิ้ง)
    คืน {groups, total} หรือ None ถ้า vault ว่าง (ให้ app.py ตก mock)"""
    cases = load_cases()
    if not cases:
        return None
    if plant:
        pf = plant.strip().casefold()
        cases = [c for c in cases if (c.get("plant") or "").strip().casefold() == pf]
    df, dt = _parse_date(date_from), _parse_date(date_to)
    if df or dt:
        keep = []
        for c in cases:
            cd = _parse_date(c.get("repair_date"))
            if cd is None or ((not df or cd >= df) and (not dt or cd <= dt)):
                keep.append(c)
        cases = keep
    groups = {}
    for c in cases:
        cat = (c.get("category") or "").strip() or (c.get("tags") or ["general"])[0]
        groups.setdefault(cat, []).append({
            "case_id": c["case_id"], "symptom": c["symptom"],
            "cause": c.get("cause", ""), "solution": c.get("solution", ""),
            "machine": c.get("machine", ""), "component": c.get("component", ""),
            "repair_date": c.get("repair_date", ""), "severity": c.get("severity", ""),
            "downtime_min": c.get("downtime_min", 0), "plant": c.get("plant", ""),
        })
    out = [{"category": k, "count": len(v), "cases": v}
           for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]
    return {"groups": out, "total": len(cases)}


def graph():
    """สร้างข้อมูล knowledge graph จากเคสจริงใน vault สำหรับหน้า #/graph
    โหนด: plant / machine / component / case / fault(category) / team(department)
    คืน {nodes, links} หรือ None ถ้า vault ว่าง (ให้ app.py ตก mock)"""
    cases = load_cases()
    if not cases:
        return None
    nodes, links, seen = {}, [], set()

    def add(nid, ntype, body=""):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "body": body}
        return nid

    def link(a, b):
        if a != b and (a, b) not in seen and (b, a) not in seen:
            seen.add((a, b))
            links.append({"source": a, "target": b})

    def ok(v):  # ค่าที่ใช้เป็นโหนดได้ (ตัดค่าว่าง/placeholder)
        v = (v or "").strip()
        return v if v and v not in ("?", "-", "_unsorted") else ""

    for c in cases:
        cid = c["case_id"]
        body = "\n".join(x for x in (
            f"อาการ: {c['symptom']}" if c.get("symptom") else "",
            f"สาเหตุ: {c['cause']}" if c.get("cause") else "",
            f"วิธีแก้: {c['solution']}" if c.get("solution") else "",
        ) if x)
        add(cid, "case", body)

        plant = ok(c.get("plant"))
        machine = ok(c.get("machine"))
        component = ok(c.get("component"))
        fault = ok(c.get("category")) or (c.get("tags") or [""])[0]
        team = ok(c.get("department"))

        if plant:
            add(plant, "plant", f"โรงงาน {plant}")
        if machine:
            add(machine, "machine", f"เครื่อง {machine}" + (f" @ {plant}" if plant else ""))
            link(cid, machine)
            if plant:
                link(machine, plant)
        if component:
            add(component, "component", f"อะไหล่/จุด {component}" + (f" ของ {machine}" if machine else ""))
            link(cid, component)
            if machine:
                link(component, machine)
        if fault:
            add(fault, "fault", f"ประเภทปัญหา: {fault}")
            link(cid, fault)
        if team:
            add(team, "team", f"ฝ่าย {team}")
            link(cid, team)

    return {"nodes": list(nodes.values()), "links": links}


def save_case_and_reindex(fields, image_path=None, image_name=None):
    """เซฟเคสผ่าน vault.save_case แล้วล้าง cache เพื่อให้ index ใหม่ทันทีรอบหน้า"""
    import vault
    status, case_id = vault.save_case(fields, image_src=image_path, image_name=image_name)
    if case_id:
        _CACHE.update(key=None, cases=None, vecs=None, vocab=None)
    return status, case_id


def save_markdown_and_reindex(md, image_path=None, image_name=None):
    """เซฟเนื้อ .md ที่ผ่านหน้าพรีวิว (อาจถูกแก้) ผ่าน vault.save_markdown แล้วล้าง cache"""
    import vault
    status, case_id = vault.save_markdown(md, image_src=image_path, image_name=image_name)
    if case_id:
        _CACHE.update(key=None, cases=None, vecs=None, vocab=None)
    return status, case_id
