"""
db.py — ต่อ MSSQL ให้ auth/users (pyodbc)

อ่านค่าจาก .env:
  DB_SERVER    เช่น localhost หรือ 10.28.255.20  (เครื่องที่รัน SQL Server)
  DB_NAME      ชื่อ database — dev ใช้ jarvis_test, prod ใช้ jarvis
  DB_DRIVER    ODBC driver, default "ODBC Driver 18 for SQL Server"
  DB_TRUSTED   "1" = Windows Authentication (เครื่องเดียวกับ DB) — ไม่ต้อง user/pass
  DB_USER / DB_PASSWORD   ใช้เมื่อ DB_TRUSTED != "1" (SQL login ข้ามเครื่อง)

*** เหมือน auth.py: ห้าม degrade เป็น mock ***
ต่อ DB ไม่ได้ = โยน error ให้ caller จัดการ (fail closed) ไม่คืนข้อมูลปลอม
ไม่งั้น "DB ล่ม" จะกลายเป็น "login ผ่านหมด/ไม่มี user"
"""
import os

import pyodbc


def _conn_str():
    server  = os.getenv("DB_SERVER", "localhost")
    name    = os.getenv("DB_NAME", "jarvis_test")   # dev default = test DB (ไม่แตะ jarvis จริง)
    driver  = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    trusted = os.getenv("DB_TRUSTED", "1") == "1"

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={name}",
        "Encrypt=yes",
        "TrustServerCertificate=yes",   # localhost/self-signed cert — ไม่งั้น Encrypt=yes จะ error
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={os.getenv('DB_USER', '')}")
        parts.append(f"PWD={os.getenv('DB_PASSWORD', '')}")
    return ";".join(parts) + ";"


def db_ready():
    """ตั้ง .env พอต่อ DB ได้ไหม + ต่อติดจริงไหม — ให้ auth เช็คก่อนเปิด login"""
    try:
        with get_conn() as c:
            c.cursor().execute("SELECT 1")
        return True
    except Exception:
        return False


def get_conn():
    """เปิด connection ใหม่ (ใช้แบบ with get_conn() as c: ...) — ปิดเองเมื่อออก block

    autocommit=True: งาน auth เป็น query/insert สั้นๆ ไม่ต้องคุม transaction เอง
    """
    return pyodbc.connect(_conn_str(), autocommit=True, timeout=5)


def query_one(sql, params=()):
    """คืนแถวแรกเป็น dict (คอลัมน์ -> ค่า) หรือ None ถ้าไม่เจอ"""
    with get_conn() as c:
        cur = c.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def query_all(sql, params=()):
    """คืนทุกแถวเป็น list[dict]"""
    with get_conn() as c:
        cur = c.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def execute(sql, params=()):
    """รัน INSERT/UPDATE/DELETE — คืนจำนวนแถวที่กระทบ"""
    with get_conn() as c:
        cur = c.cursor()
        cur.execute(sql, params)
        return cur.rowcount
