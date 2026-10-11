from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
import pandas as pd
import io
import urllib.parse
from datetime import date, datetime

app = FastAPI()

def init_db():
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    # Invoices Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        phone TEXT,
        invoice_no TEXT UNIQUE,
        pending_amount REAL,
        due_date TEXT,
        status TEXT DEFAULT 'PENDING',
        payment_mode TEXT DEFAULT '',
        paid_at TEXT DEFAULT ''
    )
    """)
    # Settings Table for Dynamic UPI / Scanner Details
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

@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    wholesaler_name, wholesaler_upi = get_settings()
    
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    
    # Stats
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE status = 'PENDING'")
    total_bills, total_amount = cursor.fetchone()
    
    today_str = str(date.today())
    cursor.execute("SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date <= ?", (today_str,))
    due_today_count = cursor.fetchone()[0]

    # Active Pending Invoices
    cursor.execute("SELECT customer_name, phone, invoice_no, pending_amount, due_date FROM receivables WHERE status = 'PENDING' ORDER BY due_date ASC")
    pending_records = cursor.fetchall()

    # Paid Invoices History
    cursor.execute("SELECT customer_name, invoice_no, pending_amount, payment_mode, paid_at FROM receivables WHERE status = 'PAID' ORDER BY id DESC LIMIT 10")
    paid_records = cursor.fetchall()
    conn.close()

    # Build Pending Table Rows
    pending_rows = ""
    for name, phone, inv, amount, due in pending_records:
        clean_phone = str(phone).replace("+", "").strip()
        if not clean_phone.startswith("91") and len(clean_phone) == 10:
            clean_phone = "91" + clean_phone
        
        pay_url = f"https://quickbill-saas.onrender.com/pay/{inv}"
        msg = f"Namaste {name},\n{wholesaler_name} ki taraf se aapka invoice #{inv} (Rs {amount:,.2f}) pending hai. Due date: {due}.\nDirect UPI se pay karein: {pay_url}"
        encoded_msg = urllib.parse.quote(msg)
        wa_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"

        pending_rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><b>{name}</b><br><small style="color:#64748b;">{clean_phone}</small></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; color:#dc2626; font-weight:bold;">Rs {amount:,.2f}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{due}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">
                <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                    <a href="{wa_link}" target="_blank" style="background:#25D366; color:white; padding:6px 10px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:bold;">Send WhatsApp</a>
                    <form action="/mark-paid/{inv}" method="post" style="margin:0; display:flex; gap:4px;">
                        <input type="hidden" name="mode" value="Cash">
                        <button type="submit" onclick="return confirm('Invoice #{inv} ko Paid as CASH mark karein?');" style="background:#059669; color:white; border:none; padding:6px 10px; border-radius:6px; font-size:12px; font-weight:bold; cursor:pointer;">Paid as Cash</button>
                    </form>
                    <form action="/mark-paid/{inv}" method="post" style="margin:0; display:flex; gap:4px;">
                        <input type="hidden" name="mode" value="UPI / Online">
                        <button type="submit" onclick="return confirm('Invoice #{inv} ko Paid as ONLINE mark karein?');" style="background:#2563eb; color:white; border:none; padding:6px 10px; border-radius:6px; font-size:12px; font-weight:bold; cursor:pointer;">Paid Online</button>
                    </form>
                </div>
            </td>
        </tr>
        """

    # Build Paid Table Rows
    paid_rows = ""
    for name, inv, amount, mode, paid_at in paid_records:
        badge_color = "#059669" if "Cash" in mode else "#2563eb"
        paid_rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><b>{name}</b></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-weight:bold;">Rs {amount:,.2f}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">
                <span style="background:{badge_color}; color:white; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:bold;">Paid as {mode}</span>
            </td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-size:12px; color:#64748b;">{paid_at}</td>
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
            .container {{ max-width: 900px; width: 100%; }}
            .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }}
            .amount {{ font-size: 24px; font-weight: bold; color: #dc2626; }}
            .count {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
            th {{ background: #f1f5f9; padding: 10px; color: #475569; }}
            input[type="text"] {{ padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 6px; width: 100%; box-sizing: border-box; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                <div>
                    <h2 style="margin:0;">QuickBill Cloud SaaS</h2>
                    <p style="color:#64748b; margin:4px 0 0 0;">Active Store: <b>{wholesaler_name}</b></p>
                </div>
            </div>

            <!-- Scanner & UPI Settings Card -->
            <div class="card" style="border-left: 4px solid #2563eb; margin-top:15px;">
                <h3 style="margin-top:0;">UPI Scanner / Receiver Settings</h3>
                <form action="/update-settings" method="post" style="display:grid; grid-template-columns: 1fr 1fr auto; gap:10px; align-items:flex-end;">
                    <div>
                        <label style="font-size:12px; font-weight:bold; color:#475569;">Business / Display Name</label>
                        <input type="text" name="wholesaler_name" value="{wholesaler_name}" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:bold; color:#475569;">UPI ID / Scanner ID (PhonePe/GPay/Paytm)</label>
                        <input type="text" name="upi_id" value="{wholesaler_upi}" required placeholder="e.g. mobile@ybl ya name@okaxis">
                    </div>
                    <div>
                        <button type="submit" class="btn">Update Scanner</button>
                    </div>
                </form>
                <small style="color:#64748b; display:block; margin-top:8px;">* Yahan jo UPI ID daalenge, sabhi customer ke payment link aur QR code par turant wahi live ho jayegi.</small>
            </div>

            <!-- Metrics -->
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
            
            <!-- Excel Upload -->
            <div class="card">
                <h3>Excel Sheet Upload Karein</h3>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom:15px; display:block; width: 100%;">
                    <button type="submit" class="btn">Upload & Save Karein</button>
                </form>
            </div>

            <!-- Active Pending Invoices -->
            <div class="card">
                <h3>Active Invoices & Actions</h3>
                <div style="overflow-x:auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Invoice</th>
                                <th>Amount</th>
                                <th>Due Date</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {pending_rows if pending_rows else '<tr><td colspan="5" style="text-align:center; padding:15px; color:#94a3b8;">Sabhi invoices clear hain ya koi record nahi mila.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Paid Records History -->
            <div class="card">
                <h3>Recent Paid Bills History</h3>
                <div style="overflow-x:auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Invoice</th>
                                <th>Amount</th>
                                <th>Payment Mode</th>
                                <th>Cleared Date & Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {paid_rows if paid_rows else '<tr><td colspan="5" style="text-align:center; padding:15px; color:#94a3b8;">Abhi tak koi paid record nahi hai.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/update-settings")
def update_settings(wholesaler_name: str = Form(...), upi_id: str = Form(...)):
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET wholesaler_name = ?, upi_id = ? WHERE id = 1", (wholesaler_name.strip(), upi_id.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/mark-paid/{invoice_no}")
def mark_as_paid(invoice_no: str, mode: str = Form(...)):
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    cursor.execute("UPDATE receivables SET status = 'PAID', payment_mode = ?, paid_at = ? WHERE invoice_no = ?", (mode, now_str, invoice_no))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/upload", response_class=HTMLResponse)
async def upload_excel(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    for _, row in df.iterrows():
        inv_no = str(row['Invoice_No']).strip()
        cursor.execute("SELECT id FROM receivables WHERE invoice_no = ?", (inv_no,))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute("""
                INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(row['Customer_Name']),
                str(row['Phone']),
                inv_no,
                float(row['Amount']),
                str(row['Due_Date'])
            ))
    conn.commit()
    conn.close()
    return "<script>alert('Excel successfully load ho gayi! Duplicate invoices ko skip kar diya gaya.'); window.location.href='/';</script>"

@app.get("/pay/{invoice_no}", response_class=HTMLResponse)
def show_payment_page(invoice_no: str):
    wholesaler_name, wholesaler_upi = get_settings()
    
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT customer_name, pending_amount, due_date, status, payment_mode, paid_at FROM receivables WHERE invoice_no = ?", (invoice_no,))
    record = cursor.fetchone()
    conn.close()
    if not record:
        return "<h3>Invoice nahi mila!</h3>"
    
    customer_name, amount, due_date, status, payment_mode, paid_at = record
    if status == 'PAID':
        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Paid - {invoice_no}</title></head>
        <body style="font-family:sans-serif; background:#f3f4f6; display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; padding:15px;">
            <div style="background:white; padding:30px; border-radius:14px; text-align:center; max-width:360px; box-shadow:0 4px 15px rgba(0,0,0,0.08);">
                <div style="background:#dcfce7; color:#16a34a; width:60px; height:60px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px; margin:0 auto 15px;">✓</div>
                <h2 style="color:#16a34a; margin:0;">Payment Cleared!</h2>
                <p style="color:#64748b; font-size:14px;">Invoice <b>#{invoice_no}</b> is already settled.</p>
                <div style="font-size:26px; font-weight:bold; color:#1e293b; margin:15px 0;">Rs {amount:,.2f}</div>
                <div style="background:#f1f5f9; padding:10px; border-radius:8px; font-size:13px; text-align:left; margin-bottom:15px;">
                    <div><b>Received as:</b> {payment_mode}</div>
                    <div><b>Date:</b> {paid_at}</div>
                </div>
                <small style="color:#64748b;">{wholesaler_name}</small>
            </div>
        </body>
        </html>
        """

    upi_link = f"upi://pay?pa={wholesaler_upi}&pn={urllib.parse.quote(wholesaler_name)}&am={amount}&cu=INR&tn=Invoice_{invoice_no}"
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={urllib.parse.quote(upi_link)}"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment - {invoice_no}</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f3f4f6; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 15px; }}
            .card {{ background: white; padding: 25px; border-radius: 14px; text-align: center; max-width: 360px; width: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .amount {{ font-size: 30px; font-weight: bold; color: #16a34a; margin: 15px 0; }}
            .pay-btn {{ display: block; background: #2563eb; color: white; text-decoration: none; padding: 12px; border-radius: 8px; font-weight: bold; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2 style="margin-bottom:5px;">{wholesaler_name}</h2>
            <p style="color:#64748b; margin-top:0;">Billed to: <b>{customer_name}</b></p>
            <div class="amount">Rs {amount:,.2f}</div>
            <p style="font-size:13px; color:#475569;">Invoice: {invoice_no} | Due: {due_date}</p>
            <img src="{qr_link}" width="220" height="220" style="margin:10px auto; border-radius:8px; border:1px solid #e2e8f0; display:block;">
            <p style="font-size:12px; color:#64748b; margin:5px 0;">PhonePe, Google Pay ya Paytm se scan karein</p>
            <small style="font-size:11px; color:#94a3b8;">Receiver UPI: {wholesaler_upi}</small>
            <a href="{upi_link}" class="pay-btn">Pay via UPI App</a>
        </div>
    </body>
    </html>
    """
