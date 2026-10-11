from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
import sqlite3
import pandas as pd
import io
import os
import urllib.parse
from datetime import date, datetime

app = FastAPI()

UPLOAD_DIR = "uploaded_qrs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        phone TEXT,
        invoice_no TEXT UNIQUE,
        pending_amount REAL,
        due_date TEXT,
        status TEXT DEFAULT 'PENDING',
        custom_qr_path TEXT DEFAULT ''
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT,
        customer_name TEXT,
        amount_paid REAL,
        remaining_balance REAL,
        payment_mode TEXT,
        paid_at TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        wholesaler_name TEXT,
        upi_id TEXT
    )
    """)
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO settings (id, wholesaler_name, upi_id) VALUES (1, 'Apex Wholesale Distributors', 'apexdistributors@upi')")
    
    # Safe migration check
    cursor.execute("PRAGMA table_info(receivables)")
    cols = [r[1] for r in cursor.fetchall()]
    if 'custom_qr_path' not in cols:
        cursor.execute("ALTER TABLE receivables ADD COLUMN custom_qr_path TEXT DEFAULT ''")

    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wholesaler_name, upi_id FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return "Apex Wholesale Distributors", "apexdistributors@upi"

@app.get("/qr-img/{filename}")
def get_qr_image(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return HTMLResponse("Image not found", status_code=404)

@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    wholesaler_name, default_upi = get_settings()
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    
    # Metrics
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE status = 'PENDING'")
    total_bills, total_amount = cursor.fetchone()
    
    today_str = str(date.today())
    cursor.execute("SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date <= ?", (today_str,))
    due_today_count = cursor.fetchone()[0]

    # Active Pending Invoices
    cursor.execute("SELECT customer_name, phone, invoice_no, pending_amount, due_date, custom_qr_path FROM receivables WHERE status = 'PENDING' ORDER BY due_date ASC")
    pending_records = cursor.fetchall()

    # Payment logs history
    cursor.execute("SELECT customer_name, invoice_no, amount_paid, remaining_balance, payment_mode, paid_at FROM payment_logs ORDER BY id DESC LIMIT 15")
    logs = cursor.fetchall()
    conn.close()

    pending_rows = ""
    for name, phone, inv, amount, due, qr_path in pending_records:
        clean_phone = str(phone).replace("+", "").strip()
        if not clean_phone.startswith("91") and len(clean_phone) == 10:
            clean_phone = "91" + clean_phone
        
        pay_url = f"https://quickbill-saas.onrender.com/pay/{inv}"
        msg = f"Namaste {name},\n{wholesaler_name} ki taraf se aapka invoice #{inv} ka Rs {amount:,.2f} pending hai. Due date: {due}.\nDirect pay karein: {pay_url}"
        encoded_msg = urllib.parse.quote(msg)
        wa_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"

        qr_status = "<span style='background:#dcfce7; color:#166534; padding:2px 6px; border-radius:4px; font-size:11px;'>Custom Scanner Active</span>" if qr_path else "<span style='color:#64748b; font-size:11px;'>Default Scanner</span>"

        pending_rows += f"""
        <tr>
            <td style="padding:12px; border-bottom:1px solid #e2e8f0;">
                <b>{name}</b><br><small style="color:#64748b;">{clean_phone}</small>
            </td>
            <td style="padding:12px; border-bottom:1px solid #e2e8f0;">
                <b>{inv}</b><br>{qr_status}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e2e8f0; color:#dc2626; font-weight:bold; font-size:16px;">
                Rs {amount:,.2f}
            </td>
            <td style="padding:12px; border-bottom:1px solid #e2e8f0;">{due}</td>
            <td style="padding:12px; border-bottom:1px solid #e2e8f0;">
                <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px;">
                    <a href="{wa_link}" target="_blank" style="background:#25D366; color:white; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:bold;">Send WhatsApp</a>
                    <button onclick="openCashModal('{inv}', '{name}', {amount})" style="background:#059669; color:white; border:none; padding:6px 10px; border-radius:6px; font-size:12px; font-weight:bold; cursor:pointer;">Paid as Cash</button>
                    <a href="{pay_url}" target="_blank" style="background:#6366f1; color:white; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:bold;">View Bill</a>
                </div>

                <!-- Custom Scanner QR Photo Upload -->
                <form action="/upload-qr/{inv}" method="post" enctype="multipart/form-data" style="display:flex; gap:4px; align-items:center;">
                    <input type="file" name="qr_file" accept="image/*" required style="font-size:11px; width:140px;">
                    <button type="submit" style="background:#334155; color:white; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">Set Scanner</button>
                </form>
            </td>
        </tr>
        """

    logs_rows = ""
    for c_name, inv, p_amt, rem, mode, p_time in logs:
        status_txt = f"Partial Paid (Bacha: Rs {rem:,.2f})" if rem > 0 else "Full Cleared"
        badge_bg = "#fef08a" if rem > 0 else "#dcfce7"
        badge_fg = "#854d0e" if rem > 0 else "#166534"
        logs_rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><b>{c_name}</b></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-weight:bold; color:#059669;">Rs {p_amt:,.2f}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">
                <span style="background:{badge_bg}; color:{badge_fg}; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:bold;">{status_txt} via {mode}</span>
            </td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-size:12px; color:#64748b;">{p_time}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>QuickBill - Cloud Dashboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f8fafc; padding: 20px; display: flex; justify-content: center; margin:0; }}
            .container {{ max-width: 950px; width: 100%; }}
            .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }}
            .amount {{ font-size: 24px; font-weight: bold; color: #dc2626; }}
            .count {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
            th {{ background: #f1f5f9; padding: 10px; color: #475569; }}

            /* Modal Style */
            .modal {{ display:none; position:fixed; z-index:100; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.5); justify-content:center; align-items:center; }}
            .modal-content {{ background:white; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 10px 25px rgba(0,0,0,0.2); }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>QuickBill Cloud SaaS</h2>
            <p style="color:#64748b; margin-top:2px;">Store: <b>{wholesaler_name}</b> | Default UPI: <b>{default_upi}</b></p>
            
            <div class="stats">
                <div class="card">
                    <div style="font-size:12px; color:#64748b; font-weight: bold;">TOTAL PENDING UDHAAR</div>
                    <div class="amount">Rs {total_amount:,.2f}</div>
                    <small>{total_bills} active invoices</small>
                </div>
                <div class="card">
                    <div style="font-size:12px; color:#64748b; font-weight: bold;">AAJ RECOVERY DUE</div>
                    <div class="count">{due_today_count}</div>
                    <small>Due date cross ho chuki hai</small>
                </div>
            </div>

            <!-- Upload Excel -->
            <div class="card">
                <h3>Excel Sheet Upload Karein</h3>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom:15px; display:block; width: 100%;">
                    <button type="submit" class="btn">Upload & Save Karein</button>
                </form>
            </div>

            <!-- Active Invoices -->
            <div class="card">
                <h3>Pending Invoices</h3>
                <div style="overflow-x:auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Invoice</th>
                                <th>Pending Due</th>
                                <th>Due Date</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {pending_rows if pending_rows else '<tr><td colspan="5" style="text-align:center; padding:15px; color:#94a3b8;">Sabhi bills clear hain!</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Payment Logs -->
            <div class="card">
                <h3>Payment Collection & Cash Adjustments History</h3>
                <div style="overflow-x:auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Invoice</th>
                                <th>Cash/Online Received</th>
                                <th>Details</th>
                                <th>Date & Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {logs_rows if logs_rows else '<tr><td colspan="5" style="text-align:center; padding:
