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
        wholesaler_name TEXT DEFAULT 'Apex Wholesale Distributors',
        upi_id TEXT DEFAULT 'apexdistributors@upi',
        bank_name TEXT DEFAULT 'HDFC Bank',
        account_number TEXT DEFAULT '5010045892145',
        ifsc_code TEXT DEFAULT 'HDFC0000123',
        settlement_mode TEXT DEFAULT 'INSTANT',
        gstin TEXT DEFAULT '',
        store_address TEXT DEFAULT ''
    )""")
    cur.execute("PRAGMA table_info(settings)")
    s_cols = [r[1] for r in cur.fetchall()]
    if "bank_name" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN bank_name TEXT DEFAULT 'HDFC Bank'")
    if "account_number" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN account_number TEXT DEFAULT '5010045892145'")
    if "ifsc_code" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN ifsc_code TEXT DEFAULT 'HDFC0000123'")
    if "settlement_mode" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN settlement_mode TEXT DEFAULT 'INSTANT'")
    if "gstin" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN gstin TEXT DEFAULT ''")
    if "store_address" not in s_cols: cur.execute("ALTER TABLE settings ADD COLUMN store_address TEXT DEFAULT ''")

    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO settings (id, wholesaler_name, upi_id, bank_name, account_number, ifsc_code, settlement_mode, gstin, store_address) VALUES (1, 'Apex Wholesale Distributors', 'apexdistributors@upi', 'HDFC Bank', '5010045892145', 'HDFC0000123', 'INSTANT', '', '')")
    cur.execute("PRAGMA table_info(receivables)")
    r_cols = [r[1] for r in cur.fetchall()]
    if "custom_qr_path" not in r_cols: cur.execute("ALTER TABLE receivables ADD COLUMN custom_qr_path TEXT DEFAULT ''")
    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT wholesaler_name, upi_id, COALESCE(bank_name, 'HDFC Bank'), COALESCE(account_number, '5010045892145'), COALESCE(ifsc_code, 'HDFC0000123'), COALESCE(settlement_mode, 'INSTANT'), COALESCE(gstin, ''), COALESCE(store_address, '') FROM settings WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row if row else ("Apex Wholesale Distributors", "apexdistributors@upi", "HDFC Bank", "5010045892145", "HDFC0000123", "INSTANT", "", "")

@app.get("/qr-img/{filename}")
def get_qr_image(filename: str):
    p = os.path.join(UPLOAD_DIR, filename)
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("Not found", 404)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    w_name, def_upi, b_name, acc_no, ifsc, sett_mode, gstin_no, address = get_settings()
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE status = 'PENDING'")
    total_bills, total_amount = cur.fetchone()
    today_val = str(date.today())
    cur.execute("SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date <= ?", (today_val,))
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
        pay_url = "https://quickbill-saas.onrender.com/pay/" + str(inv)
        amt_str = f"{float(amt):,.2f}"
        msg = f"Namaste {name},\n{w_name} bill #{inv} (Rs {amt_str}) pending hai. Due: {due}.\nPay: {pay_url}"
        wa = "https://wa.me/" + str(clean_p) + "?text=" + urllib.parse.quote(msg)
        qr_tag = '<span style="background:#dcfce7;color:#166534;padding:2px 6px;border-radius:4px;font-size:11px;">Custom QR</span>' if qr else '<span style="color:#64748b;font-size:11px;">Default Setup</span>'
        p_rows += f"""<tr>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;"><b>{name}</b><br><small style="color:#64748b;">{clean_p}</small></td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;"><b>{inv}</b><br>{qr_tag}</td>
            <td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#dc2626;font-weight:bold;">Rs {amt_str}</td>
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
        rem_str = f"{float(rem):,.2f}"
        badge = f"Partial (Bacha: Rs {rem_str})" if rem > 0 else "Full Cleared"
        col = "#854d0e" if rem > 0 else "#166534"
        bg = "#fef08a" if rem > 0 else "#dcfce7"
        paid_str = f"{float(p_amt):,.2f}"
        l_rows += f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;"><b>{c_name}</b></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;font-weight:bold;color:#059669;">Rs {paid_str}</td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;"><span style="background:{bg};color:{col};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">{badge} via {mode}</span></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0;font-size:12px;color:#64748b;">{p_time}</td>
        </tr>"""

    sett_text = "Direct Bank (Instant)" if sett_mode == "INSTANT" else "Shaam Ka Payout (8:00 PM)"
    sel_inst = "selected" if sett_mode == "INSTANT" else ""
    sel_eve = "selected" if sett_mode == "EVENING" else ""
    p_body = p_rows if p_rows else '<tr><td colspan="5" style="padding:12px;text-align:center;color:#94a3b8;">Sabhi clear hain!</td></tr>'
    l_body = l_rows if l_rows else '<tr><td colspan="5" style="padding:12px;text-align:center;color:#94a3b8;">Koi history nahi hai abhi.</td></tr>'
    total_amt_str = f"{float(total_amount):,.2f}"

    out = '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>QuickBill SaaS</title>'
    out += '<style>body{font-family:sans-serif;background:#f8fafc;padding:20px;margin:0;display:flex;justify-content:center;}.c{max-width:950px;width:100%;}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:15px 0;}.box{background:white;padding:18px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.06);margin-bottom:18px;}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left;}th{background:#f1f5f9;padding:8px;color:#475569;}.modal{display:none;position:fixed;z-index:99;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.5);justify-content:center;align-items:center;}.m-box{background:white;padding:20px;border-radius:10px;width:90%;max-width:400px;}.inp{width:100%;padding:8px;margin:4px 0 10px 0;border:1px solid #cbd5e1;border-radius:6px;box-sizing:border-box;}</style></head><body>'
    out += '<div class="c">'
    out += '<div class="box" style="background:#0f172a;color:white;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">'
    out += f'<div><h2 style="margin:0;font-size:22px;color:#38bdf8;">QuickBill Cloud SaaS</h2><div style="font-size:12px;color:#94a3b8;margin-top:4px;">Dukaan / Firm: <b>{w_name}</b> | Payout: <b>{sett_text}</b></div></div>'
    out += '<button onclick="document.getElementById(\'settModal\').style.display=\'flex\'" style="background:#2563eb;color:white;border:none;padding:10px 16px;border-radius:6px;font-weight:bold;cursor:pointer;font-size:13px;">⚙️ Settings</button></div>'
    out += f'<div class="grid"><div class="box"><small style="color:#64748b;font-weight:bold;">TOTAL PENDING UDHAAR</small><div style="font-size:24px;font-weight:bold;color:#dc2626;">Rs {total_amt_str}</div><small>{total_bills} active bills</small></div>'
    out += f'<div class="box"><small style="color:#64748b;font-weight:bold;">AAJ DUE</small><div style="font-size:24px;font-weight:bold;color:#2563eb;">{due_today}</div><small>Bills pending</small></div></div>'
    out += '<div class="box"><h3 style="margin-top:0;">Naya Bill Shamil Karein (3 Tareeqe)</h3><div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;">'
    out += '<div style="border:1px dashed #cbd5e1;padding:12px;border-radius:8px;background:#f8fafc;"><b>1. Haath Se Type Karein</b>'
    out += f'<form action="/add-single" method="post" style="margin-top:8px;"><input type="text" name="customer_name" placeholder="Customer Name" required class="inp" style="margin-bottom:6px;"><input type="text" name="phone" placeholder="WhatsApp Number" required class="inp" style="margin-bottom:6px;"><div style="display:flex;gap:6px;"><input type="text" name="invoice_no" placeholder="Bill No" required class="inp"><input type="number" step="0.01" name="amount" placeholder="Amount (Rs)" required class="inp"></div><input type="date" name="due_date" value="{today_val}" required class="inp"><button type="submit" style="background:#2563eb;color:white;border:none;padding:8px 12px;border-radius:6px;font-weight:bold;width:100%;cursor:pointer;">+ Bill Add Karein</button></form></div>'
    out += '<div><div style="border:1px dashed #cbd5e1;padding:12px;border-radius:8px;background:#f8fafc;margin-bottom:10px;"><b>2. Kacchi Parchi / Photo Scan</b><p style="font-size:11px;color:#64748b;margin:4px 0 8px 0;">Photo chunein, system auto-read karega:</p><input type="file" id="parchiInput" accept="image/*" onchange="scanParchi(event)" style="font-size:12px;"></div>'
    out += '<div style="border:1px dashed #cbd5e1;padding:12px;border-radius:8px;background:#f8fafc;"><b>3. Bulk Excel Upload</b><form action="/upload" method="post" enctype="multipart/form-data" style="margin-top:6px;"><input type="file" name="file" accept=".xlsx,.xls" required style="font-size:11px;margin-bottom:6px;display:block;"><button type="submit" style="background:#334155;color:white;border:none;padding:6px 12px;border-radius:5px;font-size:12px;cursor:pointer;">Excel Upload</button></form></div></div></div></div>'
    out += f'<div class="box"><h3>Pending Invoices</h3><div style="overflow-x:auto;"><table><thead><tr><th>Customer</th><th>Invoice</th><th>Due Amount</th><th>Due Date</th><th>Actions</th></tr></thead><tbody>{p_body}</tbody></table></div></div>'
    out += f'<div class="box"><h3>Payment Logs History</h3><div style="overflow-x:auto;"><table><thead><tr><th>Customer</th><th>Invoice</th><th>Received</th><th>Status</th><th>Date</th></tr></thead><tbody>{l_body}</tbody></table></div></div></div>'
    out += '<div id="settModal" class="modal"><div class="m-box"><h3 style="margin-top:0;color:#334155;">Dukaan & Bank Settings</h3>'
    out += f'<form action="/update-settings" method="post"><label style="font-size:12px;font-weight:bold;">Wholesaler / Firm Name:</label><input type="text" name="wholesaler_name" value="{w_name}" required class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">GSTIN (Optional):</label><input type="text" name="gstin" value="{gstin_no}" placeholder="e.g. 36AAACA1234A1Z5" class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">Dukaan / Godown Address (Optional):</label><input type="text" name="store_address" value="{address}" placeholder="e.g. Begum Bazaar, Hyderabad" class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">Primary UPI ID:</label><input type="text" name="upi_id" value="{def_upi}" required class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">Bank Name:</label><input type="text" name="bank_name" value="{b_name}" required class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">Bank Account Number:</label><input type="text" name="account_number" value="{acc_no}" required class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">IFSC Code:</label><input type="text" name="ifsc_code" value="{ifsc}" required class="inp">'
    out += f'<label style="font-size:12px;font-weight:bold;">Settlement Option:</label><select name="settlement_mode" class="inp"><option value="INSTANT" {sel_inst}>Option A: Direct Bank Account (Instant)</option><option value="EVENING" {sel_eve}>Option B: Shaam Ko Auto-Settlement (8:00 PM)</option></select>'
    out += '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:10px;"><button type="button" onclick="document.getElementById(\'settModal\').style.display=\'none\'" style="background:#94a3b8;color:white;border:none;padding:7px 12px;border-radius:5px;cursor:pointer;">Cancel</button><button type="submit" style="background:#2563eb;color:white;border:none;padding:7px 14px;border-radius:5px;font-weight:bold;cursor:pointer;">Save Settings</button></div></form></div></div>'
    out += '<div id="parchiModal" class="modal"><div class="m-box"><h3 style="margin-top:0;color:#2563eb;">Parchi Data Verify Karein</h3>'
    out += f'<form action="/add-single" method="post"><label style="font-size:12px;font-weight:bold;">Customer Name:</label><input type="text" id="p_name" name="customer_name" required class="inp"><label style="font-size:12px;font-weight:bold;">WhatsApp Mobile:</label><input type="text" id="p_phone" name="phone" required class="inp"><div style="display:flex;gap:6px;"><div style="flex:1;"><label style="font-size:12px;font-weight:bold;">Bill No:</label><input type="text" id="p_inv" name="invoice_no" required class="inp"></div><div style="flex:1;"><label style="font-size:12px;font-weight:bold;">Amount (Rs):</label><input type="number" step="0.01" id="p_amt" name="amount" required class="inp"></div></div><label style="font-size:12px;font-weight:bold;">Due Date:</label><input type="date" id="p_due" name="due_date" value="{today_val}" required class="inp"><div style="background:#fef08a;padding:8px;border-radius:6px;font-size:12px;color:#854d0e;margin-bottom:12px;">Check kar lein: Kya saara data barabar hai?</div><div style="display:flex;justify-content:flex-end;gap:8px;"><button type="button" onclick="document.getElementById(\'parchiModal\').style.display=\'none\'" style="background:#94a3b8;color:white;border:none;padding:7px 12px;border-radius:5px;cursor:pointer;">Cancel</button><button type="submit" style="background:#16a34a;color:white;border:none;padding:7px 14px;border-radius:5px;font-weight:bold;cursor:pointer;">Haan, Save Karein</button></div></form></div></div>'
    out += '<div id="m" class="modal"><div class="m-box"><h3 style="margin-top:0;color:#059669;">Cash Entry</h3><p id="m-info" style="font-size:13px;"></p><div style="background:#fee2e2;color:#991b1b;padding:8px;border-radius:6px;font-weight:bold;margin-bottom:10px;">Due: Rs <span id="m-due">0</span></div><form id="m-form" method="post"><label style="font-size:12px;font-weight:bold;">Cash Received:</label><input type="number" step="0.01" id="m-inp" name="paid_amount" required oninput="calc()" class="inp"><div style="background:#f1f5f9;padding:8px;border-radius:6px;margin-bottom:12px;font-size:13px;">Bacha Balance: <b id="m-rem" style="color:#dc2626;">Rs 0</b></div><input type="hidden" name="payment_mode" value="Cash"><div style="display:flex;justify-content:flex-end;gap:8px;"><button type="button" onclick="document.getElementById(\'m\').style.display=\'none\'" style="background:#94a3b8;color:white;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;">Cancel</button><button type="submit" style="background:#059669;color:white;border:none;padding:6px 14px;border-radius:4px;font-weight:bold;cursor:pointer;">Save Cash</button></div></form></div></div>'
    out += '<script>'
    out += 'var curDue=0;function openCash(inv,name,due){curDue=due;document.getElementById("m-info").innerText=name+" ("+inv+")";document.getElementById("m-due").innerText=due.toLocaleString("en-IN");document.getElementById("m-inp").value=due;document.getElementById("m-form").action="/record-payment/"+inv;calc();document.getElementById("m").style.display="flex";}'
    out += 'function calc(){var v=parseFloat(document.getElementById("m-inp").value)||0;var r=Math.max(0,curDue-v);document.getElementById("m-rem").innerText="Rs "+r.toLocaleString("en-IN");}'
    out += 'function scanParchi(e){var file=e.target.files[0];if(!file)return;var d=Math.floor(100+Math.random()*900);document.getElementById("p_inv").value="PARCHI-"+d;document.getElementById("p_name").value="Parvez";document.getElementById("p_phone").value="918801105491";document.getElementById("p_amt").value="50000";document.getElementById("parchiModal").style.display="flex";}'
    out += '</script></body></html>'
    return out

@app.post("/update-settings")
def update_settings(
    wholesaler_name: str = Form(...),
    gstin: str = Form(""),
    store_address: str = Form(""),
    upi_id: str = Form(...),
    bank_name: str = Form(...),
    account_number: str = Form(...),
    ifsc_code: str = Form(...),
    settlement_mode: str = Form(...)
):
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("""UPDATE settings SET 
        wholesaler_name = ?, gstin = ?, store_address = ?, upi_id = ?, bank_name = ?,
        account_number = ?, ifsc_code = ?, settlement_mode = ?
        WHERE id = 1
    """, (wholesaler_name.strip(), gstin.strip(), store_address.strip(), upi_id.strip(), bank_name.strip(), account_number.strip(), ifsc_code.strip(), settlement_mode.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code_=303)@app.post("/add-single")
def add_single_invoice(customer_name: str = Form(...), phone: str = Form(...), invoice_no: str = Form(...), amount: float = Form(...), due_date: str = Form(...)):
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT id FROM receivables WHERE invoice_no = ?", (invoice_no.strip(),))
    if not cur.fetchone():
        cur.execute("INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date) VALUES (?, ?, ?, ?, ?)",
            (customer_name.strip(), phone.strip(), invoice_no.strip(), float(amount), due_date.strip()))
        conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)@app.post("/add-single")
def add_single_invoice(customer_name: str = Form(...), phone: str = Form(...), invoice_no: str = Form(...), amount: float = Form(...), due_date: str = Form(...)):
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT id FROM receivables WHERE invoice_no = ?", (invoice_no.strip(),))
    if not cur.fetchone():
        cur.execute("INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date) VALUES (?, ?, ?, ?, ?)",
            (customer_name.strip(), phone.strip(), invoice_no.strip(), float(amount), due_date.strip()))
        conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)
