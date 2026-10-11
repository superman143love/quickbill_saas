import io
import os
import sqlite3
import urllib.parse
from datetime import date, datetime

import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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
    cursor.execute(
        "INSERT INTO settings (id, wholesaler_name, upi_id) VALUES (1, 'Apex"
        " Wholesale Distributors', 'apexdistributors@upi')"
    )

  cursor.execute("PRAGMA table_info(receivables)")
  cols = [r[1] for r in cursor.fetchall()]
  if "custom_qr_path" not in cols:
    cursor.execute(
        "ALTER TABLE receivables ADD COLUMN custom_qr_path TEXT DEFAULT ''"
    )

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

  cursor.execute(
      "SELECT COUNT(*), COALESCE(SUM(pending_amount), 0) FROM receivables WHERE"
      " status = 'PENDING'"
  )
  total_bills, total_amount = cursor.fetchone()

  today_str = str(date.today())
  cursor.execute(
      "SELECT COUNT(*) FROM receivables WHERE status = 'PENDING' AND due_date"
      " <= ?",
      (today_str,),
  )
  due_today_count = cursor.fetchone()[0]

  cursor.execute(
      "SELECT customer_name, phone, invoice_no, pending_amount, due_date,"
      " custom_qr_path FROM receivables WHERE status = 'PENDING' ORDER BY"
      " due_date ASC"
  )
  pending_records = cursor.fetchall()

  cursor.execute(
      "SELECT customer_name, invoice_no, amount_paid, remaining_balance,"
      " payment_mode, paid_at FROM payment_logs ORDER BY id DESC LIMIT 15"
  )
  logs = cursor.fetchall()
  conn.close()

  pending_rows = []
  for name, phone, inv, amount, due, qr_path in pending_records:
    clean_phone = str(phone).replace("+", "").strip()
    if not clean_phone.startswith("91") and len(clean_phone) == 10:
      clean_phone = "91" + clean_phone

    pay_url = f"https://quickbill-saas.onrender.com/pay/{inv}"
    msg = (
        f"Namaste {name},\n{wholesaler_name} ki taraf se invoice #{inv} (Rs"
        f" {amount:,.2f}) pending hai. Due date: {due}.\nDirect pay karein:"
        f" {pay_url}"
    )
    encoded_msg = urllib.parse.quote(msg)
    wa_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"

    if qr_path:
      qr_status = (
          '<span style="background:#dcfce7; color:#166534; padding:2px 6px;'
          ' border-radius:4px; font-size:11px;">Custom Scanner Active</span>'
      )
    else:
      qr_status = (
          '<span style="color:#64748b; font-size:11px;">Default Scanner</span>'
      )

    row_html = f"""
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

                <form action="/upload-qr/{inv}" method="post" enctype="multipart/form-data" style="display:flex; gap:4px; align-items:center;">
                    <input type="file" name="qr_file" accept="image/*" required style="font-size:11px; width:140px;">
                    <button type="submit" style="background:#334155; color:white; border:none; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;">Set Scanner</button>
                </form>
            </td>
        </tr>
        """
    pending_rows.append(row_html)

  logs_rows = []
  for c_name, inv, p_amt, rem, mode, p_time in logs:
    if rem > 0:
      status_txt = f"Partial Paid (Bacha: Rs {rem:,.2f})"
      badge_bg = "#fef08a"
      badge_fg = "#854d0e"
    else:
      status_txt = "Full Cleared"
      badge_bg = "#dcfce7"
      badge_fg = "#166534"

    log_html = f"""
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
    logs_rows.append(log_html)

  if pending_rows:
    final_pending_html = "".join(pending_rows)
  else:
    final_pending_html = (
        '<tr><td colspan="5" style="text-align:center; padding:15px;'
        ' color:#94a3b8;">Sabhi bills clear hain!</td></tr>'
    )

  if logs_rows:
    final_logs_html = "".join(logs_rows)
  else:
    final_logs_html = (
        '<tr><td colspan="5" style="text-align:center; padding:15px;'
        ' color:#94a3b8;">Koi payment history nahi hai abhi.</td></tr>'
    )

  return f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuickBill - Cloud Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f8fafc; padding: 20px; display: flex; justify-content: center; margin: 0; }}
        .container {{ max-width: 950px; width: 100%; }}
        .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }}
        .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }}
        .amount {{ font-size: 24px; font-weight: bold; color: #dc2626; }}
        .count {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
        .btn {{ background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
        th {{ background: #f1f5f9; padding: 10px; color: #475569; }}
        .modal {{ display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); justify-content: center; align-items: center; }}
        .modal-content {{ background: white; padding: 24px; border-radius: 12px; width: 90%; max-width: 400px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); }}
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

        <div class="card">
            <h3>Excel Sheet Upload Karein</h3>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom:15px; display:block; width: 100%;">
                <button type="submit" class="btn">Upload & Save Karein</button>
            </form>
        </div>

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
                        {final_pending_html}
                    </tbody>
                </table>
            </div>
        </div>

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
                        {final_logs_html}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="cashModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#059669;">Paid as Cash Entry</h3>
            <p style="margin:4px 0; font-size:14px;">Customer: <b id="modalCustName"></b></p>
            <p style="margin:4px 0; font-size:14px;">Invoice: <b id="modalInvNo"></b></p>
            <div style="background:#fee2e2; color:#991b1b; padding:8px; border-radius:6px; font-size:15px; font-weight:bold; margin:10px 0;">
                Total Due: Rs <span id="modalTotalDue">0</span>
            </div>

            <form id="cashForm" action="" method="post">
                <div style="margin-bottom:12px;">
                    <label style="font-size:13px; font-weight:bold; display:block; margin-bottom:4px;">Cash Kitna Receive Hua?</label>
                    <input type="number" step="0.01" id="cashInput" name="paid_amount" required oninput="calculateBalance()" style="width:100%; padding:8px; font-size:16px; border:1px solid #cbd5e1; border-radius:6px; box-sizing:border-box;">
                </div>

                <div style="background:#f1f5f9; padding:10px; border-radius:6px; margin-bottom:15px;">
                    <div style="font-size:13px; color:#475569;">Bacha Hua Udhaar (Balance):</div>
                    <div style="font-size:18px; font-weight:bold; color:#dc2626;" id="modalRemainingBalance">Rs 0.00</div>
                </div>

                <input type="hidden" name="payment_mode" value="Cash">

                <div style="display:flex; justify-content:flex-end; gap:8px;">
                    <button type="button" onclick="closeCashModal()" style="background:#94a3b8; color:white; border:none; padding:8px 14px; border-radius:6px; cursor:pointer;">Cancel</button>
                    <button type="submit" style="background:#059669; color:white; border:none; padding:8px 16px; border-radius:6px; font-weight:bold; cursor:pointer;">Save Cash Payment</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        var currentTotalDue = 0;

        function openCashModal(inv, custName, due) {{
            currentTotalDue = due;
            document.getElementById('modalInvNo').innerText = inv;
            document.getElementById('modalCustName').innerText = custName;
            document.getElementById('modalTotalDue').innerText = due.toLocaleString('en-IN', {{minimumFractionDigits: 2}});
            document.getElementById('cashInput').value = due;
            document.getElementById('cashForm').action = '/record-payment/' + inv;
            calculateBalance();
            document.getElementById('cashModal').style.display = 'flex';
        }}

        function closeCashModal() {{
            document.getElementById('cashModal').style.display = 'none';
        }}

        function calculateBalance() {{
            var entered = parseFloat(document.getElementById('cashInput').value) || 0;
            var remaining = currentTotalDue - entered;
            if (remaining < 0) remaining = 0;
            document.getElementById('modalRemainingBalance').innerText = 'Rs ' + remaining.toLocaleString('en-IN', {{minimumFractionDigits: 2}});
        }}
    </script>
</body>
</html>"""


@app.post("/upload-qr/{invoice_no}")
async def upload_custom_qr(invoice_no: str, qr_file: UploadFile = File(...)):
  ext = os.path.splitext(qr_file.filename)[1]
  saved_filename = f"qr_{invoice_no}_{int(datetime.now().timestamp())}{ext}"
  file_path = os.path.join(UPLOAD_DIR, saved_filename)
  contents = await qr_file.read()
  with open(file_path, "wb") as f:
    f.write(contents)

  conn = sqlite3.connect("udhaar_system.db")
  cursor = conn.cursor()
  cursor.execute(
      "UPDATE receivables SET custom_qr_path = ? WHERE invoice_no = ?",
      (saved_filename, invoice_no),
  )
  conn.commit()
  conn.close()
  return RedirectResponse(url="/", status_code=303)


@app.post("/record-payment/{invoice_no}")
def record_payment(
    invoice_no: str,
    paid_amount: float = Form(...),
    payment_mode: str = Form("Cash"),
):
  conn = sqlite3.connect("udhaar_system.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT customer_name, pending_amount FROM receivables WHERE invoice_no ="
      " ?",
      (invoice_no,),
  )
  row = cursor.fetchone()
  if row:
    c_name, current_due = row
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    paid_amt = min(paid_amount, current_due)
    remaining = current_due - paid_amt

    cursor.execute(
        """
            INSERT INTO payment_logs (invoice_no, customer_name, amount_paid, remaining_balance, payment_mode, paid_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        (invoice_no, c_name, paid_amt, remaining, payment_mode, now_str),
    )

    if remaining <= 0.01:
      cursor.execute(
          "UPDATE receivables SET pending_amount = 0, status = 'PAID' WHERE"
          " invoice_no = ?",
          (invoice_no,),
      )
    else:
      cursor.execute(
          "UPDATE receivables SET pending_amount = ? WHERE invoice_no = ?",
          (remaining, invoice_no),
      )

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
    inv_no = str(row["Invoice_No"]).strip()
    cursor.execute(
        "SELECT id FROM receivables WHERE invoice_no = ?", (inv_no,)
    )
    exists = cursor.fetchone()
    if not exists:
      cursor.execute(
          """
                INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date)
                VALUES (?, ?, ?, ?, ?)
            """,
          (
              str(row["Customer_Name"]),
              str(row["Phone"]),
              inv_no,
              float(row["Amount"]),
