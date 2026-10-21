import io, os, sqlite3, urllib.parse
from datetime import date, datetime
import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

app = FastAPI()
UPLOAD_DIR = "uploaded_qrs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT, phone TEXT, invoice_no TEXT UNIQUE,
        pending_amount REAL, due_date TEXT, status TEXT DEFAULT 'PENDING',
        custom_qr_path TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT, customer_name TEXT, amount_paid REAL,
        remaining_balance REAL, payment_mode TEXT, paid_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        wholesaler_name TEXT,
        upi_id TEXT,
        bank_name TEXT DEFAULT 'HDFC Bank',
        account_number TEXT DEFAULT '5010045892145',
        ifsc_code TEXT DEFAULT 'HDFC0000123',
        settlement_mode TEXT DEFAULT 'INSTANT'
    )""")
    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        cur.execute("""INSERT INTO settings VALUES 
            (1, 'Apex Wholesale Distributors', 'apexdistributors@upi', 'HDFC Bank', '5010045892145', 'HDFC0000123', 'INSTANT')""")
    
    cur.execute("PRAGMA table_info(settings)")
    cols = [r[1] for r in cur.fetchall()]
    if "bank_name" not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN bank_name TEXT DEFAULT 'HDFC Bank'")
    if "account_number" not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN account_number TEXT DEFAULT '5010045892145'")
    if "ifsc_code" not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN ifsc_code TEXT DEFAULT 'HDFC0000123'")
    if "settlement_mode" not in cols:
        cur.execute("ALTER TABLE settings ADD COLUMN settlement_mode TEXT DEFAULT 'INSTANT'")

    cur.execute("PRAGMA table_info(receivables)")
    r_cols = [r[1] for r in cur.fetchall()]
    if "custom_qr_path" not in r_cols:
        cur.execute("ALTER TABLE receivables ADD COLUMN custom_qr_path TEXT DEFAULT ''")

    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT wholesaler_name, upi_id, bank_name, account_number, ifsc_code, settlement_mode FROM settings WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return row
    return ("Apex Wholesale Distributors", "apexdistributors@upi", "HDFC Bank", "5010045892145", "HDFC0000123", "INSTANT")

@app.get("/qr-img/{filename}")
def get_qr_image(filename: str):
    p = os.path.join(UPLOAD_DIR, filename)
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("Not found", 404)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    w_name, def_upi, b_name, acc_no, ifsc, sett_mode = get_settings()
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE status = 'PENDING'")
    total_bills, total_amount = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date <= ?", (str(date.today()),))
    due_today = cur.fetchone()[0]
    cur.execute("SELECT customer_name, phone, invoice_no, pending_amount, due_date, custom_qr_path FROM receivables WHERE status = 'PENDING' ORDER BY due_date ASC")
    pending = cur.fetchall()
    cur.execute("SELECT customer_name, invoice_no, amount_paid, remaining_balance, payment_mode, paid_at FROM payment_logs ORDER BY id DESC LIMIT 15")
    logs = cur.fetchall()
    conn.close()

    p_rows = ""
    for name, phone, inv, amt, due, qr in pending:
        clean_p = str(phone).replace("+", "").strip()
        if not clean_p.startswith("91") and len(clean_p) == 10: clean_p = "91" + clean_p
        pay_url = f"https://quickbill-saas.onrender.com/pay/{inv}"
        msg = f"Namaste {name},\n{w_name} invoice #{inv} (Rs {amt:,.2f}) pending. Due: {due}.\nOnline / Bank Pay: {pay_url}"
        wa = f"https://wa.me/{clean_p}?text={urllib.parse.quote(msg)}"
        qr_tag = '<span style="background:#dcfce7;color:#166534;padding:2px 6px;border-radius:4px;font-size:11px;">Custom QR</span>' if qr else '<span style="color:#64748b;font-size:11px;">Default Setup</span>'
        p_rows += f"""<tr>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;"><b>{name}</b><br><small style="color:#64748b;">{clean_p}</small></td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;"><b>{inv}</b><br>{qr_tag}</td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#dc2626;font-weight:bold;">Rs {amt:,.2f}</td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;">{due}</td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;">
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
                    <a href="{wa}" target="_blank" style="background:#25D366;color:white;padding:5px 9px;border-radius:5px;text-decoration:none;font-size:12px;font-weight:bold;">WhatsApp</a>
                    <button onclick="openCash('{inv}', '{name}', {amt})" style="background:#059669;color:white;border:none;padding:5px 9px;border-radius:5px;font-size:12px;font-weight:bold;cursor:pointer;">Paid as Cash</button>
                    <a href="{pay_url}" target="_blank" style="background:#6366f1;color:white;padding:5px 9px;border-radius:5px;text-decoration:none;font-size:12px;font-weight:bold;">View Bill</a>
                </div>
                <form action="/upload-qr/{inv}" method="post" enctype="multipart/form-data" style="display:flex;gap:4px;">
                    <input type="file" name="qr_file" accept="image/*" required style="font-size:11px;width:130px;">
                    <button type="submit" style="background:#334155;color:white;border:none;padding:3px 6px;border-radius:4px;font-size:11px;cursor:pointer;">Set QR</button>
                </form>
            </td>
        </tr>"""

    l_rows = ""
    for c_name, inv, p_amt, rem, mode, p_time in logs:
        badge = f"Partial (Bacha: Rs {rem:,.2f})" if rem > 0 else "Full Cleared"
        col = "#854d0e" if rem > 0 else "#166534"
        bg = "#fef08a" if rem > 0 else "#dcfce7"
        l_rows += f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;"><b>{c_name}</b></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;font-weight:bold;color:#059669;">Rs {p_amt:,.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;"><span style="background:{bg};color:{col};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">{badge} via {mode}</span></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;font-size:12px;color:#64748b;">{p_time}</td>
        </tr>"""

    today_val = str(date.today())
    sett_text = "Instant Bank Settlement" if sett_mode == "INSTANT" else "Daily Evening Payout (8:00 PM)"

    html = """<!DOCTYPE html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuickBill SaaS</title>
    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>
    <style>
        body { font-family: sans-serif; background: #f8fafc; padding: 20px; margin: 0; display:flex; justify-content:center; }
        .c { max-width: 950px; width: 100%; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0; }
        .box { background: white; padding: 18px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 18px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
        th { background: #f1f5f9; padding: 8px; color: #475569; }
        .modal { display:none; position:fixed; z-index:99; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.5); justify-content:center; align-items:center; }
        .m-box { background:white; padding:20px; border-radius:10px; width:90%; max-width:400px; }
        .inp { width:100%; padding:8px; margin:4px 0 10px 0; border:1px solid #cbd5e1; border-radius:6px; box-sizing:border-box; }
    </style></head><body>
    <div class="c">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
            <div>
                <h2 style="margin:0;">QuickBill Cloud SaaS</h2>
                <p style="color:#64748b; margin:4px 0;">Store: <b>__W_NAME__</b> | Mode: <span style="background:#e0e7ff; color:#3730a3; padding:2px 8px; border-radius:12px; font-size:12px; font-weight:bold;">__SETT_TEXT__</span></p>
            </div>
            <button onclick="document.getElementById('settModal').style.display='flex'" style="background:#334155; color:white; border:none; padding:8px 14px; border-radius:6px; font-weight:bold; cursor:pointer; font-size:12px;">⚙️ Bank & Payout Settings</button>
        </div>
        
        <div class="grid">
            <div class="box"><small style="color:#64748b;font-weight:bold;">TOTAL PENDING</small><div style="font-size:24px;font-weight:bold;color:#dc2626;">Rs __TOTAL_AMT__</div><small>__TOTAL_BILLS__ active</small></div>
            <div class="box"><small style="color:#64748b;font-weight:bold;">AAJ DUE</small><div style="font-size:24px;font-weight:bold;color:#2563eb;">__DUE_TODAY__</div><small>Bills due</small></div>
        </div>

        <div class="box">
            <h3 style="margin-top:0;">Naya Bill Shamil Karein (3 Tareeqe)</h3>
            <div style="display:grid; grid-template-columns: 1fr 1fr;
