"""
auth.py — login + JWT ของ JARVIS (บัญชีอยู่ในตาราง users บน MSSQL)

เดิมอ่านบัญชีจาก .env — ตอนนี้ query ตาราง dbo.users แทน (ดู db.py)
รหัสเก็บเป็น bcrypt hash ในคอลัมน์ password_hash — ห้ามเก็บ plaintext

*** ต่างจากโมดูลอื่นในโปรเจกต์นี้ตรงที่ "ห้าม degrade เป็น mock" ***
llm.py / rag.py / transcribe.py ต่อ backend ไม่ติดแล้วคืน mock เพื่อให้เดโมไหลต่อ
แต่ auth ห้ามทำแบบนั้น — DB ต่อไม่ได้ / ไม่ตั้ง JWT_SECRET = ปฏิเสธ login ทุกกรณี (fail closed)
ไม่งั้น "DB ล่ม" กลายเป็น "ใครก็ login ได้"
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt   # PyJWT

import db

# ── config จาก .env (ไม่มีค่า default สำหรับความลับ — ไม่ตั้ง = login ไม่ได้) ──
JWT_SECRET     = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM  = "HS256"
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))   # อายุ token (นาที)

# hash ปลอมไว้เทียบเวลา user ไม่มีจริง — ให้ bcrypt ทำงานเท่ากันทั้ง 2 ทาง
# กัน timing attack ที่ใช้เวลาตอบต่างกันเดาว่ามี username นี้ไหม
_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()


def hash_password(plain: str) -> str:
    """แปลงรหัสเป็น bcrypt hash (เก็บลง password_hash) — คืน str"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode()


def status_line():
    """ข้อความสรุปสถานะ auth ให้ app.py พิมพ์ตอน startup (นับ user อย่างเดียว)

    ห้ามพิมพ์ตอน import! app.py ตั้ง stdout เป็น utf-8 "หลัง" บรรทัด import
    """
    if not JWT_SECRET:
        return "[auth] ยังไม่ได้ตั้ง JWT_SECRET -> login ปิดไว้"
    try:
        n = db.query_one("SELECT COUNT(*) AS n FROM dbo.users WHERE is_active = 1")["n"]
        return f"[auth] ต่อ DB ({os.getenv('DB_NAME', 'jarvis_test')}) ได้: {n} บัญชีใช้งานอยู่"
    except Exception as e:
        return f"[auth] ต่อ DB ไม่ได้ -> login ปิดไว้ ({type(e).__name__})"


def auth_ready():
    """ตั้ง .env ครบ + ต่อ DB ได้ไหม (ต้องมีกุญแจเซ็น token + DB reachable)"""
    return bool(JWT_SECRET) and db.db_ready()


def verify_login(username, password):
    """เทียบ username/password กับ dbo.users — คืน dict ของ user ถ้าผ่าน, None ถ้าไม่

    - query เฉพาะ is_active=1 (บัญชีถูกปิด = login ไม่ได้)
    - ไม่เจอ user ก็ยัง checkpw กับ hash ปลอม เพื่อให้เวลาตอบเท่ากัน (กัน enumeration)
    """
    if not JWT_SECRET:
        return None
    try:
        u = db.query_one(
            "SELECT id, username, password_hash, role, first_name, last_name "
            "FROM dbo.users WHERE username = ? AND is_active = 1",
            (username,),
        )
    except Exception:
        return None   # DB ล่ม = ปฏิเสธ (fail closed) ไม่ปล่อยผ่าน

    stored = u["password_hash"] if u else _DUMMY_HASH
    try:
        ok = bcrypt.checkpw((password or "").encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        ok = False
    if u and ok:
        # อัพเดทเวลา login ล่าสุด (best-effort — ล้มก็ไม่บล็อก login)
        try:
            db.execute("UPDATE dbo.users SET last_login_at = SYSUTCDATETIME() WHERE id = ?", (u["id"],))
        except Exception:
            pass
        return u
    return None


def create_token(user):
    """ออก JWT ให้ user (dict จาก verify_login) — ใส่ role จริงจาก DB

    รับ dict {id, username, role, ...} — ไม่ hardcode role แล้ว
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["username"],
        "uid": user["id"],
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    """ตรวจลายเซ็น + วันหมดอายุ — คืน payload ถ้าใช้ได้, None ถ้าไม่ผ่าน

    ระบุ algorithms ตายตัว: ห้ามให้ token เป็นคนบอกว่าใช้ algorithm ไหน (กัน alg=none)
    """
    if not JWT_SECRET:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ── จัดการ user (ใช้โดย /api/register — admin เท่านั้น) ──────────────

def username_exists(username, email=None, employee_id=None):
    """เช็คซ้ำก่อน insert — คืน field ที่ชนถ้ามี ('username'|'email'|'employee_id') ไม่งั้น None"""
    row = db.query_one(
        "SELECT "
        "  SUM(CASE WHEN username = ? THEN 1 ELSE 0 END)    AS u, "
        "  SUM(CASE WHEN email = ? THEN 1 ELSE 0 END)       AS e, "
        "  SUM(CASE WHEN employee_id = ? THEN 1 ELSE 0 END) AS emp "
        "FROM dbo.users",
        (username, email or "", employee_id or ""),
    )
    if row["u"]:   return "username"
    if row["e"]:   return "email"
    if row["emp"]: return "employee_id"
    return None


def create_user(username, password, first_name, last_name, employee_id, email,
                phone=None, role="user"):
    """เพิ่ม user ใหม่ (รหัส hash ก่อนเก็บ) — คืน id ที่เพิ่ง insert

    ผู้เรียก (app.py) ต้องเช็คสิทธิ์ admin + validate มาก่อนแล้ว
    """
    row = db.query_one(
        "INSERT INTO dbo.users "
        "(username, password_hash, first_name, last_name, employee_id, email, phone, role) "
        "OUTPUT INSERTED.id "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (username, hash_password(password), first_name, last_name,
         employee_id, email, phone, role),
    )
    return row["id"]


def list_users():
    """รายชื่อ user ทั้งหมด (ไม่รวม password_hash) — ให้หน้า admin โชว์"""
    return db.query_all(
        "SELECT id, username, first_name, last_name, employee_id, email, phone, "
        "role, is_active, created_at, last_login_at "
        "FROM dbo.users ORDER BY id"
    )
