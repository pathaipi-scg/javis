import React, { useEffect, useState } from 'react'

// Dashboard — ตัวเลขสรุปจากเคสจริงใน vault (นับสด ไม่มี DB)

export default function DashboardPage() {
  const [data, setData] = useState(null)   // {stats, categories, mock}
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/dashboard')
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError('โหลดไม่ได้ — ตรวจว่ารัน backend (demo/app.py) ที่พอร์ต 5000 แล้ว'))
  }, [])

  const max = data ? Math.max(...data.categories.map((c) => c.count), 1) : 1

  return (
    <section className="case-wrap">
      <div className="case-card">
        <div className="case-head">
          <h2>📊 Dashboard
            {data?.mock && <span className="mock-badge">MOCK — vault ว่าง</span>}
          </h2>
          <span className="case-sub">สรุปจากเคสจริงใน vault — นับสดทุกครั้งที่เปิด</span>
        </div>

        {error && <div className="case-error">{error}</div>}
        {!data && !error && <div className="hist-empty">กำลังโหลด…</div>}

        {data && (
          <>
            <div className="db-stats">
              <div className="db-stat">
                <div className="db-num">{data.stats.total}</div>
                <div className="db-label">เคสทั้งหมด</div>
              </div>
              <div className="db-stat">
                <div className="db-num">{data.stats.machines}</div>
                <div className="db-label">เครื่องจักร</div>
              </div>
              <div className="db-stat">
                <div className="db-num">{data.stats.downtime.toLocaleString()}</div>
                <div className="db-label">Downtime รวม (นาที)</div>
              </div>
            </div>

            <label style={{ marginTop: 26 }}>เคสตามหมวด (category/tag)</label>
            <div className="db-bars">
              {data.categories.map((c) => (
                <div key={c.name} className="db-bar-row">
                  <span className="db-bar-name">#{c.name}</span>
                  <div className="db-bar-track">
                    <div className="db-bar-fill" style={{ width: (c.count / max * 100) + '%' }} />
                  </div>
                  <span className="db-bar-count">{c.count}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
