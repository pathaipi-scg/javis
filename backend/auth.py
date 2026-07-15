"""
auth.py — login + JWT ของ JARVIS (ตอนนี้มีแค่บัญชี admin ตัวเดียวไว้ทดสอบ)

แนวคิด: เทียบ username/password กับค่าใน .env ตรงๆ (ยังไม่มี DB ผู้ใช้)
  ADMIN_USERNAME  / ADMIN_PASSWORD   -> บัญชีที่ 1
  ADMIN2_USERNAME / ADMIN2_PASSWORD  -> บัญชีที่ 2
  ADMIN3_USERNAME / ADMIN3_PASSWORD  -> บัญชีที่ 3   (เพิ่มได้ถึง ADMIN10_*)
  JWT_SECRET                         -> กุญแจเซ็น token (ต้องตั้งเอง ไม่มีค่า default)

*** ต่างจากโมดูลอื่นในโปรเจกต์นี้ตรงที่ "ห้าม degrade เป็น mock" ***
llm.py / rag.py / transcribe.py ออกแบบให้ต่อ backend ไม่ติดแล้วคืน mock เพื่อให้เดโมไหลต่อได้
แต่ auth ห้ามทำแบบนั้นเด็ดขาด — ตั้ง env ไม่ครบ = ปฏิเสธ login ทุกกรณี (fail closed)
ไม่งั้น "ลืมตั้ง .env" จะกลายเป็น "ใครก็ login ได้"
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt   # PyJWT

# ── config จาก .env (ไม่มีค่า default สำหรับความลับ — ไม่ตั้ง = login ไม่ได้) ──
# หมายเหตุ: ห้ามใช้ชื่อ USERNAME! Windows ตั้ง env USERNAME ไว้อยู่แล้ว (= ชื่อ user ที่ล็อกอินเครื่อง)
# แล้ว load_dotenv() ก็ไม่ override ของเดิม -> os.getenv("USERNAME") จะได้ชื่อ user ของ Windows
# ไม่ใช่ค่าที่เขียนใน .env -> จึงใช้ ADMIN_USERNAME ที่ไม่ชนกับใคร
JWT_SECRET     = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM  = "HS256"
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))   # อายุ token (นาที)

MAX_ADMINS = 10   # เพดานที่วิ่งหาใน .env (ADMIN2_* .. ADMIN10_*)


def _load_users():
    """อ่านบัญชีทั้งหมดจาก .env -> {username: password}

    คนที่ 1 ใช้ชื่อเดิม ADMIN_USERNAME/ADMIN_PASSWORD (ของเดิมไม่ต้องแก้)
    คนถัดไปเติมเลข: ADMIN2_USERNAME/ADMIN2_PASSWORD, ADMIN3_... ไปเรื่อยๆ

    ไม่ตั้งรหัสเฉพาะตัว (ADMIN2_PASSWORD) -> ตกมาใช้ ADMIN_PASSWORD ร่วมกัน
    ตั้งเฉพาะตัวเมื่อไหร่ อันนั้นชนะ -> ผสมกันได้ (บางคนรหัสร่วม บางคนรหัสส่วนตัว)
    ระวัง: รหัสร่วมกัน = ใครรู้รหัสก็ login เป็นชื่อไหนก็ได้ ชื่อจึงเป็นแค่ป้าย ไม่ใช่ตัวตน

    ไม่มี ADMIN_PASSWORD และไม่มีรหัสเฉพาะตัว = ข้ามบัญชีนั้น (กันบัญชีรหัสว่างหลุดเข้าไป)

    ทำไมไม่ใช้ ADMIN_USERS=user1:pass1,user2:pass2 บรรทัดเดียว:
    รหัสที่มี ":" หรือ "," อยู่ข้างในจะพังทันที — แยกตัวแปรปลอดภัยกว่า
    """
    users = {}
    shared = os.getenv("ADMIN_PASSWORD", "")   # รหัสกลาง ใช้เมื่อคนนั้นไม่ได้ตั้งรหัสของตัวเอง
    keys = [("ADMIN_USERNAME", "ADMIN_PASSWORD")]
    keys += [(f"ADMIN{i}_USERNAME", f"ADMIN{i}_PASSWORD") for i in range(2, MAX_ADMINS + 1)]
    for ukey, pkey in keys:
        u = os.getenv(ukey, "").strip()
        p = os.getenv(pkey, "") or shared
        if u and p:
            users[u] = p
    return users


USERS = _load_users()


def status_line():
    """ข้อความสรุปสถานะ auth (นับอย่างเดียว — ไม่บอกชื่อ/รหัส) ให้ app.py พิมพ์ตอน startup

    ห้ามพิมพ์ตอน import! app.py ตั้ง stdout เป็น utf-8 "หลัง" บรรทัด import
    -> print ภาษาไทยตอน import จะเจอ cp1252 ของ Windows แล้ว UnicodeEncodeError ตั้งแต่เปิดเซิร์ฟเวอร์
    """
    return (f"[auth] โหลดบัญชีจาก .env: {len(USERS)} คน"
            + ("" if JWT_SECRET else " (ยังไม่ได้ตั้ง JWT_SECRET -> login ปิดไว้)"))


def auth_ready():
    """ตั้ง .env ครบพอให้ login ได้ไหม (ต้องมีอย่างน้อย 1 บัญชี + กุญแจเซ็น token)"""
    return bool(USERS and JWT_SECRET)


def _same(a, b):
    """เทียบสตริงแบบเวลาคงที่ (กัน timing attack)

    ต้อง .encode() เป็น bytes ก่อน! secrets.compare_digest รับ str ได้เฉพาะ ASCII
    ถ้าโยนภาษาไทย/อักขระพิเศษเข้าไปตรงๆ มันโยน TypeError -> login พัง 500
    """
    return secrets.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def verify_login(username, password):
    """เทียบ username/password กับบัญชีใน .env — คืน True/False

    ใช้ compare_digest แทน == เพื่อกัน timing attack:
    == หยุดทันทีที่เจอตัวอักษรต่างตัวแรก -> เวลาที่ใช้บอกใบ้ว่าเดาถูกกี่ตัว

    วนครบทุกบัญชีเสมอ ไม่ break ตอนเจอ และเทียบทั้ง user/รหัสเสมอ (ใช้ & ไม่ใช่ and)
    -> เวลาที่ใช้เท่ากันหมด ไม่บอกใบ้ว่ามี username นี้อยู่จริงไหม
    """
    if not auth_ready():
        return False
    ok = False
    for u, p in USERS.items():
        ok |= _same(username, u) & _same(password, p)
    return ok


def create_token(username):
    """ออก JWT ให้ user — มี exp/iat กัน token ใช้ได้ตลอดชีพ"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,          # เจ้าของ token
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    """ตรวจลายเซ็น + วันหมดอายุ — คืน payload ถ้าใช้ได้, None ถ้าไม่ผ่าน

    ระบุ algorithms ตายตัว: ห้ามให้ token เป็นคนบอกว่าใช้ algorithm ไหน
    (ไม่งั้นโดน alg=none / เปลี่ยนเป็น HS256 ปลอมลายเซ็น)
    """
    if not JWT_SECRET:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
