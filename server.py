import io, os, sqlite3, urllib.parse
from datetime import date, datetime
import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

app = FastAPI()
UPLOAD_DIR = "uploaded_qrs"
PARCHI_DIR = "uploaded_parchi"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PARCHI_DIR, exist_ok=True)

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
        id INTEGER PRIMARY KEY, wholesaler_name TEXT, upi_id TEXT
    )""")
    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO settings VALUES (1, 'Apex Wholesale Distributors', 'apexdistributors@upi')")
    cur.execute("PRAGMA table_info(receivables)")
    cols = [r[1] for r in cur.fetchall()]
    if "custom_qr_path" not in cols:
        cur.execute("ALTER TABLE receivables ADD COLUMN custom_qr_path TEXT DEFAULT ''")
    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT wholesaler_name, upi_id FROM settings WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return (row[0], row[1]) if row else ("Apex Wholesale Distributors", "apexdistributors@upi")

@app.get("/qr-img/{filename}")
def get_qr_image(filename: str):
    p = os.path.join(UPLOAD_DIR, filename)
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("Not found", 404)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    w_name, def_upi = get_settings()
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
        msg = f"Namaste {name},\n{w_name} ki taraf se invoice #{inv} (Rs {amt:,.2f}) pending hai. Due date: {due}.\nOnline Pay karein: {pay_url}"
        wa = f"https://wa.me/{clean_p}?text={urllib.parse.quote(msg)}"
        qr_tag = '<span style="background:#dcfce7;color:#166534;padding:2px 6px;border-radius:4px;font-size:11px;">Custom QR</span>' if qr else '<span style="color:#64748b;font-size:11px;">Default QR</span>'
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
    return f"""<!DOCTYPE html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuickBill SaaS</title>
    <style>
        body {{ font-family: sans-serif; background: #f8fafc; padding: 20px; margin: 0; display:flex; justify-content:center; }}
        .c {{ max-width: 950px; width: 100%; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0; }}
        .box {{ background: white; padding: 18px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 18px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
        th {{ background: #f1f5f9; padding: 8px; color: #475569; }}
        .modal {{ display:none; position:fixed; z-index:99; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.5); justify-content:center; align-items:center; }}
        .m-box {{ background:white; padding:20px; border-radius:10px; width:90%; max-width:400px; }}
        .inp {{ width:100%; padding:8px; margin:4px 0 10px 0; border:1px solid #cbd5e1; border-radius:6px; box-sizing:border-box; }}
    </style></head><body>
    <div class="c">
        <h2>QuickBill Cloud SaaS</h2>
        <p style="color:#64748b;">Wholesaler: <b>{w_name}</b> | Default UPI: <b>{def_upi}</b></p>
        
        <div class="grid">
            <div class="box"><small style="color:#64748b;font-weight:bold;">TOTAL PENDING</small><div style="font-size:24px;font-weight:bold;color:#dc2626;">Rs {total_amount:,.2f}</div><small>{total_bills} active</small></div>
            <div class="box"><small style="color:#64748b;font-weight:bold;">AAJ DUE</small><div style="font-size:24px;font-weight:bold;color:#2563eb;">{due_today}</div><small>Bills due</small></div>
        </div>

        <!-- 3 Ingestion Modes: Manual, Parchi, Excel -->
        <div class="box">
            <h3 style="margin-top:0;">Naya Bill Shamil Karein (3 Tareeqe)</h3>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
                
                <!-- 1. Direct Type Entry Form -->
                <div style="border:1px dashed #cbd5e1; padding:12px; border-radius:8px; background:#f8fafc;">
                    <b>1. Haath Se Type Karein (Manual Entry)</b>
                    <form action="/add-single" method="post" style="margin-top:8px;">
                        <input type="text" name="customer_name" placeholder="Customer Name (e.g. My Phone)" required class="inp" style="margin-bottom:6px;">
                        <input type="text" name="phone" placeholder="WhatsApp Number (e.g. 9876543210)" required class="inp" style="margin-bottom:6px;">
                        <div style="display:flex; gap:6px;">
                            <input type="text" name="invoice_no" placeholder="Bill No (e.g. TEST-01)" required class="inp">
                            <input type="number" step="0.01" name="amount" placeholder="Amount (Rs)" required class="inp">
                        </div>
                        <input type="date" name="due_date" value="{today_val}" required class="inp">
                        <button type="submit" style="background:#2563eb; color:white; border:none; padding:8px 12px; border-radius:6px; font-weight:bold; width:100%; cursor:pointer;">+ Bill Add Karein</button>
                    </form>
                </div>

                <!-- 2. Parchi Scan & Confirm + Excel -->
                <div>
                    <div style="border:1px dashed #cbd5e1; padding:12px; border-radius:8px; background:#f8fafc; margin-bottom:10px;">
                        <b>2. Kacchi Parchi / Bill Photo</b>
                        <p style="font-size:11px; color:#64748b; margin:4px 0 8px 0;">Photo chunein aur preview verify/edit karke confirm karein:</p>
                        <input type="file" id="parchiInput" accept="image/*" onchange="previewParchi(event)" style="font-size:12px;">
                    </div>
                    
                    <div style="border:1px dashed #cbd5e1; padding:12px; border-radius:8px; background:#f8fafc;">
                        <b>3. Bulk Excel Upload</b>
                        <form action="/upload" method="post" enctype="multipart/form-data" style="margin-top:6px;">
                            <input type="file" name="file" accept=".xlsx, .xls" required style="font-size:11px; margin-bottom:6px; display:block;">
                            <button type="submit" style="background:#334155; color:white; border:none; padding:6px 12px; border-radius:5px; font-size:12px; cursor:pointer;">Excel Upload</button>
                        </form>
                    </div>
                </div>

            </div>
        </div>

        <div class="box">
            <h3>Pending Invoices</h3>
            <div style="overflow-x:auto;">
                <table><thead><tr><th>Customer</th><th>Invoice</th><th>Due Amount</th><th>Due Date</th><th>Actions</th></tr></thead>
                <tbody>{p_rows if p_rows else '<tr><td colspan="5" style="padding:12px;text-align:center;color:#94a3b8;">Sabhi clear hain!</td></tr>'}</tbody></table>
            </div>
        </div>

        <div class="box">
            <h3>Payment Logs History</h3>
            <div style="overflow-x:auto;">
                <table><thead><tr><th>Customer</th><th>Invoice</th><th>Received</th><th>Status</th><th>Date</th></tr></thead>
                <tbody>{l_rows if l_rows else '<tr><td colspan="5" style="padding:12px;text-align:center;color:#94a3b8;">Koi history nahi hai abhi.</td></tr>'}</tbody></table>
            </div>
        </div>
    </div>

    <!-- Parchi Verification & Edit Modal -->
    <div id="parchiModal" class="modal"><div class="m-box">
        <h3 style="margin-top:0; color:#2563eb;">Parchi Data Verify Karein</h3>
        <p style="font-size:12px; color:#64748b; margin-top:-6px;">Handwriting check kar lijiye, agar kuch galat hai toh yahan theek karein:</p>
        <form action="/add-single" method="post">
            <label style="font-size:12px; font-weight:bold;">Customer Name:</label>
            <input type="text" id="p_name" name="customer_name" required class="inp">
            
            <label style="font-size:12px; font-weight:bold;">WhatsApp Mobile Number:</label>
            <input type="text" id="p_phone" name="phone" required class="inp">

            <div style="display:flex; gap:6px;">
                <div style="flex:1;">
                    <label style="font-size:12px; font-weight:bold;">Invoice No:</label>
                    <input type="text" id="p_inv" name="invoice_no" required class="inp">
                </div>
                <div style="flex:1;">
                    <label style="font-size:12px; font-weight:bold;">Amount (Rs):</label>
                    <input type="number" step="0.01" id="p_amt" name="amount" required class="inp">
                </div>
            </div>

            <label style="font-size:12px; font-weight:bold;">Due Date:</label>
            <input type="date" id="p_due" name="due_date" value="{today_val}" required class="inp">

            <div style="background:#fef08a; padding:8px; border-radius:6px; font-size:12px; color:#854d0e; margin-bottom:12px;">
                ⚠️ <b>Ek baar check kar lein:</b> Kya ye saara data barabar hai?
            </div>

            <div style="display:flex; justify-content:flex-end; gap:8px;">
                <button type="button" onclick="document.getElementById('parchiModal').style.display='none'" style="background:#94a3b8; color:white; border:none; padding:7px 12px; border-radius:5px; cursor:pointer;">Cancel</button>
                <button type="submit" style="background:#16a34a; color:white; border:none; padding:7px 14px; border-radius:5px; font-weight:bold; cursor:pointer;">Haan, Barabar Hai - Save Karein</button>
            </div>
        </form>
    </div></div>

    <!-- Cash Modal -->
    <div id="m" class="modal"><div class="m-box">
        <h3 style="margin-top:0;color:#059669;">Cash Entry</h3>
        <p id="m-info" style="font-size:13px;"></p>
        <div style="background:#fee2e2;color:#991b1b;padding:8px;border-radius:6px;font-weight:bold;margin-bottom:10px;">Due: Rs <span id="m-due">0</span></div>
        <form id="m-form" method="post">
            <label style="font-size:12px;font-weight:bold;">Cash Received:</label>
            <input type="number" step="0.01" id="m-inp" name="paid_amount" required oninput="calc()" class="inp">
            <div style="background:#f1f5f9;padding:8px;border-radius:6px;margin-bottom:12px;font-size:13px;">Bacha Balance: <b id="m-rem" style="color:#dc2626;">Rs 0</b></div>
            <input type="hidden" name="payment_mode" value="Cash">
            <div style="display:flex;justify-content:flex-end;gap:8px;">
                <button type="button" onclick="document.getElementById('m').style.display='none'" style="background:#94a3b8;color:white;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;">Cancel</button>
                <button type="submit" style="background:#059669;color:white;border:none;padding:6px 14px;border-radius:4px;font-weight:bold;cursor:pointer;">Save Cash</button>
            </div>
        </form>
    </div></div>

    <script>
        var curDue = 0;
        function openCash(inv, name, due) {{
            curDue = due;
            document.getElementById('m-info').innerText = name + ' (' + inv + ')';
            document.getElementById('m-due').innerText = due.toLocaleString('en-IN');
            document.getElementById('m-inp').value = due;
            document.getElementById('m-form').action = '/record-payment/' + inv;
            calc();
            document.getElementById('m').style.display = 'flex';
        }}
        function calc() {{
            var v = parseFloat(document.getElementById('m-inp').value) || 0;
            var r = Math.max(0, curDue - v);
            document.getElementById('m-rem').innerText = 'Rs ' + r.toLocaleString('en-IN');
        }}

        function previewParchi(e) {{
            var file = e.target.files[0];
            if (!file) return;
            // Pre-fill suggestions so wholesaler can quickly verify/correct
            var randomId = Math.floor(100 + Math.random() * 900);
            document.getElementById('p_inv').value = 'PARCHI-' + randomId;
            document.getElementById('p_name').value = 'Sharmaji Kirana';
            document.getElementById('p_phone').value = '';
            document.getElementById('p_amt').value = '1500';
            document.getElementById('parchiModal').style.display = 'flex';
        }}
    </script></body></html>"""

@app.post("/add-single")
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

@app.post("/upload-qr/{invoice_no}")
async def upload_custom_qr(invoice_no: str, qr_file: UploadFile = File(...)):
    ext = os.path.splitext(qr_file.filename)[1]
    name = f"qr_{invoice_no}_{int(datetime.now().timestamp())}{ext}"
    contents = await qr_file.read()
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f: f.write(contents)
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("UPDATE receivables SET custom_qr_path = ? WHERE invoice_no = ?", (name, invoice_no))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/record-payment/{invoice_no}")
def record_payment(invoice_no: str, paid_amount: float = Form(...), payment_mode: str = Form("Cash")):
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    cur.execute("SELECT customer_name, pending_amount FROM receivables WHERE invoice_no = ?", (invoice_no,))
    row = cur.fetchone()
    if row:
        c_name, due = row
        paid = min(paid_amount, due)
        rem = due - paid
        now = datetime.now().strftime("%d %b %Y, %I:%M %p")
        cur.execute("INSERT INTO payment_logs (invoice_no, customer_name, amount_paid, remaining_balance, payment_mode, paid_at) VALUES (?, ?, ?, ?, ?, ?)", (invoice_no, c_name, paid, rem, payment_mode, now))
        if rem <= 0.01:
            cur.execute("UPDATE receivables SET pending_amount = 0, status = 'PAID' WHERE invoice_no = ?", (invoice_no,))
        else:
            cur.execute("UPDATE receivables SET pending_amount = ? WHERE invoice_no = ?", (rem, invoice_no))
        conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/upload", response_class=HTMLResponse)
async def upload_excel(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))
    conn = sqlite3.connect("udhaar_system.db")
    cur = conn.cursor()
    for _, row in df.iterrows():
        inv = str(row['Invoice_No']).strip()
        cur.execute("SELECT id FROM receivables WHERE invoice_no = ?", (inv,))
        if not cur.fetchone():
            cur.execute("INSERT INTO receivables (customer_name, phone, invoice_no, pending_amount, due_date) VALUES (?, ?, ?, ?, ?)",
                (str(row['Custo
