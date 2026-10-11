from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
import sqlite3
import pandas as pd
import io
from datetime import date
import pywhatkit as kit
import time

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
    conn.close()

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>QuickBill - Dashboard</title>
        <style>
            body {{ font-family: sans-serif; background: #f8fafc; padding: 25px; display: flex; justify-content: center; }}
            .container {{ max-width: 600px; width: 100%; }}
            .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
            .card {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); margin-bottom: 20px; }}
            .amount {{ font-size: 24px; font-weight: bold; color: #dc2626; }}
            .count {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
            .btn {{ background: #2563eb; color: white; border: none; padding: 12px; width: 100%; border-radius: 8px; font-weight: bold; cursor: pointer; }}
            .btn-green {{ background: #16a34a; margin-top: 10px; }}
            .btn-green:hover {{ background: #15803d; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>QuickBill SaaS Dashboard</h2>
            <p style="color:#64748b;">Welcome, {WHOLESALER_NAME}</p>
            <div class="stats">
                <div class="card">
                    <div style="font-size:12px; color:#64748b;">TOTAL PENDING UDHAAR</div>
                    <div class="amount">Rs {total_amount:,.2f}</div>
                    <small>{total_bills} active invoices</small>
                </div>
                <div class="card">
                    <div style="font-size:12px; color:#64748b;">AAJ RECOVERY DUE</div>
                    <div class="count">{due_today_count}</div>
                    <small>Due date cross ho chuki hai</small>
                </div>
            </div>
            
            <div class="card">
                <h3>1. Excel Sheet Upload</h3>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom:15px; display:block;">
                    <button type="submit" class="btn">Upload & Save Karein</button>
                </form>
            </div>

            <div class="card">
                <h3>2. WhatsApp Dispatcher</h3>
                <p style="color:#64748b; font-size:14px;">In {due_today_count} customers ko personalized payment link WhatsApp karein.</p>
                <form action="/send-reminders" method="post">
                    <button type="submit" class="btn btn-green">Send Due WhatsApp Reminders</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

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

@app.post("/send-reminders", response_class=HTMLResponse)
def trigger_reminders():
    today_str = str(date.today())
    conn = sqlite3.connect("udhaar_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, phone, invoice_no, pending_amount 
        FROM receivables 
        WHERE status = 'PENDING' AND due_date <= ?
    """, (today_str,))
    records = cursor.fetchall()
    conn.close()

    count = 0
    for name, phone, inv_no, amount in records:
        pay_url = f"http://localhost:8000/pay/{inv_no}"
        msg = f"Namaste {name},\nAapka Invoice #{inv_no} ka Rs {amount:,.2f} due hai.\nPayment link: {pay_url}"
        
        # Phone number formatting check (+91)
        phone_clean = str(phone).replace(".0", "").strip()
        if not phone_clean.startswith("+"):
            phone_clean = "+91" + phone_clean
            
        try:
            kit.sendwhatmsg_instantly(phone_clean, msg, wait_time=12, tab_close=True, close_time=2)
            time.sleep(3)
            count += 1
        except Exception as e:
            print(f"Error sending to {phone_clean}: {e}")

    return f"<script>alert('{count} reminders process ho gaye!'); window.location.href='/';</script>"

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
            body {{ font-family: sans-serif; background: #f3f4f6; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
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
