from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
import sqlite3
import pandas as pd
import io
import urllib.parse
from datetime import date

app = FastAPI()

WHOLESALER_UPI = "apexdistributors@upi"
WHOLESALER_NAME = "Apex Wholesale Distributors"

def init_db():
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        phone TEXT,
        invoice_no TEXT,
        pending_amount REAL,
        due_date TEXT,
        status TEXT DEFAULT 'PENDING'
    )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE status = 'PENDING'")
    total_bills, total_amount = cursor.fetchone()
    today_str = str(date.today())
    cursor.execute("SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date <= ?", (today_str,))
    due_today_count = cursor.fetchone()[0]

    cursor.execute("SELECT customer_name, phone, invoice_no, pending_amount, due_date FROM receivables WHERE status = 'PENDING' ORDER BY due_date ASC")
    records = cursor.fetchall()
    conn.close()

    table_rows = ""
    for name, phone, inv, amount, due in records:
        clean_phone = str(phone).replace("+", "").strip()
        if not clean_phone.startswith("91") and len(clean_phone) == 10:
            clean_phone = "91" + clean_phone
        
        pay_url = f"https://quickbill-saas.onrender.com/pay/{inv}"
        msg = f"Namaste {name},\n{WHOLESALER_NAME} ki taraf se aapka invoice #{inv} (Rs {amount:,.2f}) pending hai. Due date: {due}.\nDirect UPI se pay karein: {pay_url}"
        encoded_msg = urllib.parse.quote(msg)
        wa_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"

        table_rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><b>{name}</b><br><small style="color:#64748b;">{clean_phone}</small></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{inv}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; color:#dc2626; font-weight:bold;">Rs {amount:,.2f}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{due}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">
                <a href="{wa_link}" target="_blank" style="background:#25D366; color:white; padding:6px 12px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:bold; display:inline-block;">Send WhatsApp</a>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>QuickBill - Dashboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f8fafc; padding: 20px; display: flex; justify-content: center; }}
            .container {{ max-width: 800px; width: 100%; }}
            .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }}
            .amount {{ font-size: 24px; font-weight: bold; color: #dc2626; }}
            .count {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 12px; width: 100%; border-radius: 8px; font-weight: bold; cursor: pointer; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
            th {{ background: #f1f5f9; padding: 10px; color: #475569; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>QuickBill Cloud SaaS</h2>
            <p style="color:#64748b;">Welcome, {WHOLESALER_NAME}</p>
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
            
            <div class="card">
                <h3>Excel Sheet Upload Karein</h3>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom:15px; display:block; width: 100%;">
                    <button type="submit" class="btn">Upload & Save Karein</button>
                </form>
            </div>

            <div class="card">
                <h3>Active Invoices & WhatsApp Reminder</h3>
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
                            {table_rows if table_rows else '<tr><td colspan="5" style="text-align:center; padding:15px; color:#94a3b8;">Koi record nahi mila. Excel upload karein.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/upload", response_class=HTMLResponse)
async def upload_excel(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    for _, row in df.iterrows():
        cursor.execute("""
            INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(row['Customer_Name']),
            str(row['Phone']),
            str(row['Invoice_No']),
            float(row['Amount']),
            str(row['Due_Date'])
        ))
    conn.commit()
    conn.close()
    return "<script>alert('Excel successfully load ho gayi!'); window.location.href='/';</script>"

@app.get("/pay/{invoice_no}", response_class=HTMLResponse)
def show_payment_page(invoice_no: str):
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT customer_name, pending_amount, due_date FROM receivables WHERE invoice_no = ?", (invoice_no,))
    record = cursor.fetchone()
    conn.close()
    if not record:
        return "<h3>Invoice nahi mila!</h3>"
    customer_name, amount, due_date = record
    upi_link = f"upi://pay?pa={WHOLESALER_UPI}&pn={WHOLESALER_NAME}&am={amount}&cu=INR&tn=Invoice_{invoice_no}"
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={upi_link}"
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
            .pay-btn {{ display: block; background: #2563eb; color: white; text-decoration: none; padding: 12px; border-radius: 8px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>{WHOLESALER_NAME}</h2>
            <p>Billed to: <b>{customer_name}</b></p>
            <div class="amount">Rs {amount:,.2f}</div>
            <p>Invoice: {invoice_no} | Due: {due_date}</p>
            <img src="{qr_link}" width="200" height="200" style="margin-bottom:15px;">
            <p style="font-size:12px; color:#64748b;">PhonePe, GPay ya Paytm se scan karein</p>
            <a href="{upi_link}" class="pay-btn">Pay via UPI App</a>
        </div>
    </body>
    </html>
    """
