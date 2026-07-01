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
# embeddings/LLM ใช้ Ollama ตัวเดียวกับ llm.py (OpenAI-compatible)
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "http://localhost:11434/v1")
QWEN_API_KEY  = os.getenv("QWEN_API_KEY", "not-needed")

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


def _parse_case_file(path):
    """อ่าน cases/<id>.md (สเปก tag-first) -> case dict เดียว"""
    txt = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(txt)
    tags = [t.strip() for t in fm.get("tags", "").strip("[] ").split(",") if t.strip()]
    symptom  = _parse_section(txt, "อาการ")
    cause    = _parse_section(txt, "สาเหตุ")
    solution = _parse_section(txt, "วิธีแก้")
    machine   = fm.get("machine", "?")
    component = fm.get("component", "")
    category  = fm.get("category", "")
    plant      = fm.get("plant", "")
    department = fm.get("department", "")
    try:
        downtime = int(re.sub(r"\D", "", fm.get("downtime_min", "0")) or 0)
    except Exception:
        downtime = 0
    blob = (f"เครื่อง {machine} {component} โรงงาน {plant} ฝ่าย {department} "
            f"หมวด {category} อาการ {symptom} "
            f"สาเหตุ {cause} วิธีแก้ {solution} {' '.join(tags)}")
    return {
        "case_id":  fm.get("case_id", path.stem),
        "machine":  machine,
        "symptom":  symptom or "(ไม่ระบุอาการ)",
        "solution": solution or "(ไม่ระบุวิธีแก้)",
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


def load_cases():
    """อ่านเคสจาก cases/ (สเปก tag-first) — 1 ไฟล์ = 1 เคส"""
    if not VAULT_PATH:
        return []
    cdir = Path(VAULT_PATH) / "cases"
    if not cdir.exists():
        return []
    cases = []
    # rglob = อ่านลึกทุกชั้น cases/<plant>/<dept>/... (ไม่งั้นเคสในโฟลเดอร์ย่อยจะค้นไม่เจอ)
    for f in sorted(cdir.rglob("MTN-*.md")):
        try:
            cases.append(_parse_case_file(f))
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
        return [c for _, c in scored[:k]]
    except Exception as e:
        print(f"[RAG] search ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ตก mock")
        return None


def answer(query, k=4, plant=None):
    """RAG: ดึงเคสที่เกี่ยว -> Typhoon สรุป. คืน {text, citations} หรือ None
    plant: จำกัดขอบเขตให้ตอบจากเคสในโรงงานนั้นเท่านั้น"""
    try:
        hits = search(query, k=k, plant=plant)
        if hits is None:
            return None                     # vault ว่าง/backend มีปัญหา -> ให้ app ตก mock
        if not hits:
            # โรงงานนี้ไม่มีเคสที่เกี่ยว -> ตอบชัดว่าไม่พบ (ไม่ดึงข้ามโรงงาน ไม่ mock)
            where = f"โรงงาน {plant}" if plant else "ระบบ"
            return {"text": f"ไม่พบเคสที่เกี่ยวข้องใน{where}", "citations": []}
        from llm import QWEN_MODEL
        client = _get_client()
        ctx = "\n".join(
            f"[{h['case_id']}] โรงงาน: {h.get('plant') or '-'} ฝ่าย: {h.get('department') or '-'} "
            f"เครื่อง {h['machine']} อาการ: {h['symptom']} "
            f"จุด: {h['component']} วิธีแก้: {h['solution']}"
            for h in hits
        )
        prompt = (
            "คุณคือผู้ช่วยช่างซ่อมบำรุง ตอบคำถามจากเคสที่ให้มาเท่านั้น สั้นกระชับเป็นภาษาไทย "
            "แต่ละเคสระบุโรงงาน/ฝ่ายไว้ ถ้าคำถามเจาะจงโรงงานใด ให้นับ/ตอบเฉพาะเคสของโรงงานนั้น "
            "ถ้าข้อมูลไม่พอให้บอกว่าไม่พบเคสที่ตรง\n\n"
            f"เคสที่เกี่ยวข้อง:\n{ctx}\n\nคำถาม: {query}\n\nคำตอบ:"
        )
        resp = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        return {"text": text, "citations": [h["case_id"] for h in hits]}
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


def save_case_and_reindex(fields, image_path=None, image_name=None):
    """เซฟเคสผ่าน vault.save_case แล้วล้าง cache เพื่อให้ index ใหม่ทันทีรอบหน้า"""
    import vault
    status, case_id = vault.save_case(fields, image_src=image_path, image_name=image_name)
    if case_id:
        _CACHE.update(key=None, cases=None, vecs=None)
    return status, case_id
