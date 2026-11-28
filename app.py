from flask import Flask, render_template, request, redirect, session, flash, Response
import os, sqlite3, csv, io, math, json
import urllib.request
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'wahid_hr_pro_system_v2_2026'
KSA_TZ = timezone(timedelta(hours=3))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def get_ksa_time():
    return datetime.now(KSA_TZ)

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def get_db():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        return conn, True
    conn = sqlite3.connect('attendance.db')
    return conn, False

def run_query(conn, is_pg, query, params=(), fetch=None):
    if is_pg:
        query = query.replace('?', '%s')
    cur = conn.cursor()
    cur.execute(query, params)
    res = None
    if fetch == 'one':
        res = cur.fetchone()
    elif fetch == 'all':
        res = cur.fetchall()
    cur.close()
    return res

def safe_alter(conn, is_pg, sql):
    try:
        run_query(conn, is_pg, sql)
        conn.commit()
    except Exception:
        conn.rollback()

def init_db():
    conn, is_pg = get_db()
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS shifts (id {pk}, name TEXT UNIQUE, shift_type TEXT DEFAULT 'single', start1 TEXT DEFAULT '08:00', end1 TEXT DEFAULT '16:00', start2 TEXT DEFAULT '', end2 TEXT DEFAULT '', grace_period INTEGER DEFAULT 15)")
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS employees (id {pk}, emp_id TEXT UNIQUE, name TEXT, department TEXT, job_title TEXT, assigned_branch TEXT, assigned_shift TEXT DEFAULT 'الوردية الصباحية', base_salary REAL DEFAULT 3000, password TEXT, role TEXT)")
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS branches (id {pk}, name TEXT, lat REAL, lon REAL, radius INTEGER, start_time TEXT DEFAULT '08:00', end_time TEXT DEFAULT '16:00', grace_period INTEGER DEFAULT 15)")
    run_query(conn, is_pg, f'CREATE TABLE IF NOT EXISTS attendance (id {pk}, emp_id TEXT, branch_name TEXT, date TEXT, check_in TEXT, check_out TEXT, work_hours TEXT, late_minutes INTEGER DEFAULT 0, overtime_minutes INTEGER DEFAULT 0, ip_address TEXT)')
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS leave_requests (id {pk}, emp_id TEXT, emp_name TEXT, req_type TEXT, req_date TEXT, duration_text TEXT, reason TEXT, status TEXT DEFAULT 'قيد المراجعة', created_at TEXT)")
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS advances (id {pk}, emp_id TEXT, emp_name TEXT, adv_type TEXT, amount REAL, deduct_month TEXT, reason TEXT, status TEXT DEFAULT 'قيد المراجعة', created_at TEXT)")
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS emp_documents (id {pk}, emp_id TEXT, emp_name TEXT, doc_type TEXT, doc_number TEXT, expiry_date TEXT, notes TEXT)")
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS evaluations (id {pk}, emp_id TEXT, emp_name TEXT, eval_month TEXT, score INTEGER DEFAULT 100, bonus REAL DEFAULT 0, notes TEXT, UNIQUE(emp_id, eval_month))")

    conn.commit()

    safe_alter(conn, is_pg, "ALTER TABLE employees ADD COLUMN assigned_shift TEXT DEFAULT 'الوردية الصباحية'")
    safe_alter(conn, is_pg, "ALTER TABLE employees ADD COLUMN base_salary REAL DEFAULT 3000")
    safe_alter(conn, is_pg, "ALTER TABLE attendance ADD COLUMN late_minutes INTEGER DEFAULT 0")
    safe_alter(conn, is_pg, "ALTER TABLE attendance ADD COLUMN overtime_minutes INTEGER DEFAULT 0")

    s_count = run_query(conn, is_pg, "SELECT COUNT(*) FROM shifts", fetch='one')
    if s_count[0] == 0:
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)", ('الوردية الصباحية', 'single', '08:00', '16:00', '', '', 15))
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)", ('الوردية المسائية', 'single', '16:00', '00:00', '', '', 15))
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)", ('الوردية الليلية', 'single', '00:00', '08:00', '', '', 15))
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)", ('دوام فترتين (متقطع)', 'split', '08:00', '12:00', '16:00', '20:00', 15))
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)", ('الوردية المرنة (8 ساعات)', 'flexible', '08:00', '16:00', '', '', 0))

    e_count = run_query(conn, is_pg, "SELECT COUNT(*) FROM employees", fetch='one')
    if e_count[0] == 0:
        run_query(conn, is_pg, "INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, assigned_shift, base_salary, password, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  ('admin', 'وحيد - مدير الموارد البشرية', 'الإدارة العليا', 'مدير النظام', 'جميع الفروع', 'الوردية الصباحية', 0, generate_password_hash('123456'), 'admin'))
    conn.commit()
    conn.close()

init_db()

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def time_to_mins(t_str):
    parts = t_str.split(':')
    return int(parts[0]) * 60 + int(parts[1])

def span_mins(start_hm, end_hm):
    s, e = time_to_mins(start_hm), time_to_mins(end_hm)
    return (e - s) if e > s else (1440 - s + e)

def worked_span_mins(in_hms, out_hms):
    s, e = time_to_mins(in_hms), time_to_mins(out_hms)
    return (e - s) if e >= s else (1440 - s + e)

def format_mins(mins):
    mins = int(mins or 0)
    if mins <= 0:
        return "0 د"
    if mins < 60:
        return f"{mins} د"
    return f"{mins // 60} س و {mins % 60} د"
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'emp_id' in session:
        return redirect('/dashboard')
    if request.method == 'POST':
        conn, is_pg = get_db()
        user = run_query(conn, is_pg, "SELECT emp_id, name, job_title, assigned_branch, password, role FROM employees WHERE emp_id = ?",
                         (request.form['emp_id'].strip(),), fetch='one')
        conn.close()
        if user and check_password_hash(user[4], request.form['password'].strip()):
            session['emp_id'], session['name'], session['job_title'], session['assigned_branch'], session['role'] = user[0], user[1], user[2], user[3], user[5]
            return redirect('/dashboard')
        flash('بيانات الدخول غير صحيحة')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'emp_id' not in session or 'role' not in session:
        session.clear()
        return redirect('/')
    now = get_ksa_time()
    today = now.strftime('%Y-%m-%d')
    emp_filter = request.args.get('emp_id', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    conn, is_pg = get_db()
    emp_row = run_query(conn, is_pg, "SELECT COALESCE(assigned_shift, 'الوردية الصباحية') FROM employees WHERE emp_id = ?", (session['emp_id'],), fetch='one')
    shift_name = emp_row[0] if emp_row else 'الوردية الصباحية'
    shift_info = run_query(conn, is_pg, "SELECT shift_type FROM shifts WHERE name = ?", (shift_name,), fetch='one')
    shift_type = shift_info[0] if shift_info else 'single'

    open_rec = run_query(conn, is_pg, "SELECT id, branch_name, date, check_in FROM attendance WHERE emp_id = ? AND check_out IS NULL ORDER BY id DESC LIMIT 1", (session['emp_id'],), fetch='one')
    done_row = run_query(conn, is_pg, "SELECT COUNT(*) FROM attendance WHERE emp_id = ? AND date = ? AND check_out IS NOT NULL", (session['emp_id'], today), fetch='one')
    today_done_count = int(done_row[0]) if done_row else 0
    max_sessions = 2 if shift_type == 'split' else 1

    query = "SELECT a.id, a.emp_id, e.name, e.department, a.branch_name, a.date, a.check_in, a.check_out, a.work_hours, COALESCE(a.late_minutes, 0), COALESCE(a.overtime_minutes, 0) FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE 1=1"
    params = []
    if session['role'] == 'employee':
        query += " AND a.emp_id = ?"
        params.append(session['emp_id'])
    elif session['role'] == 'supervisor' and session.get('assigned_branch') != 'جميع الفروع':
        query += " AND e.assigned_branch = ?"
        params.append(session['assigned_branch'])
    if emp_filter:
        query += " AND a.emp_id = ?"
        params.append(emp_filter)
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
    query += " ORDER BY a.id DESC"
    raw_records = run_query(conn, is_pg, query, tuple(params), fetch='all')
    records = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], format_mins(r[9]), r[10], format_mins(r[10])) for r in raw_records]
    
    stats, employees, branches = {}, [], []
    if session['role'] in ('admin', 'supervisor'):
        if session['role'] == 'supervisor' and session.get('assigned_branch') != 'جميع الفروع':
            employees = run_query(conn, is_pg, "SELECT emp_id, name FROM employees WHERE assigned_branch = ?", (session['assigned_branch'],), fetch='all')
            branches = run_query(conn, is_pg, "SELECT id, name FROM branches WHERE name = ?", (session['assigned_branch'],), fetch='all')
        else:
            employees = run_query(conn, is_pg, "SELECT emp_id, name FROM employees", fetch='all')
            branches = run_query(conn, is_pg, "SELECT id, name FROM branches", fetch='all')
        present = run_query(conn, is_pg, "SELECT COUNT(DISTINCT emp_id) FROM attendance WHERE date = ?", (today,), fetch='one')
        active = run_query(conn, is_pg, "SELECT COUNT(*) FROM attendance WHERE check_out IS NULL", fetch='one')
        pending_leaves = run_query(conn, is_pg, "SELECT COUNT(*) FROM leave_requests WHERE status = 'قيد المراجعة'", fetch='one')
        stats = {'total_emp': len(employees), 'present_today': present[0] if present else 0, 'active_now': active[0] if active else 0, 'pending_leaves': pending_leaves[0] if pending_leaves else 0}
    conn.close()
    return render_template('dashboard.html', page='dashboard', now_time=now.strftime('%H:%M:%S'), now_date=today, open_rec=open_rec, today_done_count=today_done_count, max_sessions=max_sessions, shift_name=shift_name, records=records, stats=stats, employees=employees, branches=branches, emp_filter=emp_filter, start_date=start_date, end_date=end_date)


@app.route('/payroll')
def payroll_page():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    month = request.args.get('month', get_ksa_time().strftime('%Y-%m'))
    conn, is_pg = get_db()
    emps = run_query(conn, is_pg, "SELECT emp_id, name, department, job_title, COALESCE(base_salary, 3000) FROM employees WHERE emp_id != 'admin' ORDER BY id ASC", fetch='all')
    payroll_data = []
    for e in emps:
        emp_id, name, dept, title, base_sal = e[0], e[1], e[2], e[3], float(e[4] or 0)
        att = run_query(conn, is_pg, "SELECT COUNT(DISTINCT date), COALESCE(SUM(late_minutes), 0), COALESCE(SUM(overtime_minutes), 0) FROM attendance WHERE emp_id = ? AND date LIKE ?", (emp_id, f"{month}%"), fetch='one')
        days_present, late_m, ot_m = (int(att[0] or 0), int(att[1] or 0), int(att[2] or 0)) if att else (0, 0, 0)
        adv_row = run_query(conn, is_pg, "SELECT COALESCE(SUM(amount), 0) FROM advances WHERE emp_id = ? AND deduct_month = ? AND status = 'معتمد ✅'", (emp_id, month), fetch='one')
        adv_deduct = round(float(adv_row[0] or 0), 2) if adv_row else 0.0
        ev_row = run_query(conn, is_pg, "SELECT COALESCE(SUM(bonus), 0) FROM evaluations WHERE emp_id = ? AND eval_month = ?", (emp_id, month), fetch='one')
        eval_bonus = round(float(ev_row[0] or 0), 2) if ev_row else 0.0
        minute_rate = base_sal / (30 * 8 * 60) if base_sal > 0 else 0
        late_deduct = round(late_m * minute_rate, 2)
        ot_bonus = round(ot_m * minute_rate * 1.5, 2)
        net_salary = round(max(0, base_sal - late_deduct - adv_deduct + ot_bonus + eval_bonus), 2)
        payroll_data.append({
            'emp_id': emp_id, 'name': name, 'department': dept, 'job_title': title,
            'base_salary': base_sal, 'days': days_present,
            'late_txt': format_mins(late_m), 'late_deduct': late_deduct,
            'ot_txt': format_mins(ot_m), 'ot_bonus': ot_bonus,
            'eval_bonus': eval_bonus, 'adv_deduct': adv_deduct, 'net_salary': net_salary
        })
    conn.close()
    return render_template('payroll.html', page='payroll', month=month, payroll_data=payroll_data)

@app.route('/my_payslip')
def my_payslip():
    if 'emp_id' not in session:
        return redirect('/')
    month = request.args.get('month', get_ksa_time().strftime('%Y-%m'))
    conn, is_pg = get_db()
    emp = run_query(conn, is_pg, "SELECT emp_id, name, department, job_title, assigned_branch, COALESCE(assigned_shift, 'الوردية الصباحية'), COALESCE(base_salary, 3000) FROM employees WHERE emp_id = ?", (session['emp_id'],), fetch='one')
    base_sal = float(emp[6] or 0) if emp else 0.0
    att = run_query(conn, is_pg, "SELECT COUNT(DISTINCT date), COALESCE(SUM(late_minutes), 0), COALESCE(SUM(overtime_minutes), 0) FROM attendance WHERE emp_id = ? AND date LIKE ?", (session['emp_id'], f"{month}%"), fetch='one')
    days_present, late_m, ot_m = (int(att[0] or 0), int(att[1] or 0), int(att[2] or 0)) if att else (0, 0, 0)
    adv_row = run_query(conn, is_pg, "SELECT COALESCE(SUM(amount), 0) FROM advances WHERE emp_id = ? AND deduct_month = ? AND status = 'معتمد ✅'", (session['emp_id'], month), fetch='one')
    adv_deduct = round(float(adv_row[0] or 0), 2) if adv_row else 0.0
    ev_row = run_query(conn, is_pg, "SELECT COALESCE(SUM(bonus), 0), COALESCE(MAX(score), 0) FROM evaluations WHERE emp_id = ? AND eval_month = ?", (session['emp_id'], month), fetch='one')
    eval_bonus = round(float(ev_row[0] or 0), 2) if ev_row else 0.0
    eval_score = int(ev_row[1] or 0) if ev_row else 0
    minute_rate = base_sal / (30 * 8 * 60) if base_sal > 0 else 0
    late_deduct = round(late_m * minute_rate, 2)
    ot_bonus = round(ot_m * minute_rate * 1.5, 2)
    net_salary = round(max(0, base_sal - late_deduct - adv_deduct + ot_bonus + eval_bonus), 2)
    slip = {
        'emp_id': emp[0], 'name': emp[1], 'department': emp[2], 'job_title': emp[3],
        'branch': emp[4], 'shift': emp[5], 'base_salary': base_sal, 'days': days_present,
        'late_txt': format_mins(late_m), 'late_deduct': late_deduct,
        'ot_txt': format_mins(ot_m), 'ot_bonus': ot_bonus,
        'eval_bonus': eval_bonus, 'eval_score': eval_score,
        'adv_deduct': adv_deduct, 'net_salary': net_salary
    }
    conn.close()
    return render_template('my_payslip.html', page='my_payslip', month=month, slip=slip)

    conn.close()
    return render_template('dashboard.html', page='dashboard', now_time=now.strftime('%H:%M:%S'), now_date=today, open_rec=open_rec, today_done_count=today_done_count, max_sessions=max_sessions, shift_name=shift_name, records=records, stats=stats, employees=employees, branches=branches, emp_filter=emp_filter, start_date=start_date, end_date=end_date)

@app.route('/advances')
def advances_page():
    if 'emp_id' not in session:
        return redirect('/')
    curr_month = get_ksa_time().strftime('%Y-%m')
    conn, is_pg = get_db()
    if session['role'] == 'admin':
        advances = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, adv_type, amount, deduct_month, reason, status FROM advances ORDER BY id DESC", fetch='all')
    else:
        advances = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, adv_type, amount, deduct_month, reason, status FROM advances WHERE emp_id = ? ORDER BY id DESC", (session['emp_id'],), fetch='all')
    conn.close()
    return render_template('advances.html', page='advances', curr_month=curr_month, advances=advances)

@app.route('/submit_advance', methods=['POST'])
def submit_advance():
    if 'emp_id' not in session:
        return redirect('/')
    adv_type = request.form['adv_type']
    amount = float(request.form['amount'])
    deduct_month = request.form['deduct_month']
    reason = request.form['reason'].strip()
    now_str = get_ksa_time().strftime('%Y-%m-%d %H:%M')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "INSERT INTO advances (emp_id, emp_name, adv_type, amount, deduct_month, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'قيد المراجعة', ?)",
              (session['emp_id'], session['name'], adv_type, amount, deduct_month, reason, now_str))
    conn.commit()
    conn.close()
    flash('✅ تم إرسال طلب السُلفة/العُهدة للإدارة بنجاح!')
    send_telegram(f"💵 طلب سُلفة/عُهدة ({adv_type})\nالموظف: {session['name']} ({session['emp_id']})\nالمبلغ: {amount} ر.س\nشهر الاستقطاع: {deduct_month}\nالسبب: {reason}")
    return redirect('/advances')

@app.route('/handle_advance/<int:adv_id>/<decision>')
def handle_advance(adv_id, decision):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    status = 'معتمد ✅' if decision == 'approve' else 'مرفوض ❌'
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE advances SET status = ? WHERE id = ?", (status, adv_id))
    conn.commit()
    conn.close()
    flash(f'تم تحديث حالة الطلب إلى: {status}')
    return redirect('/advances')

@app.route('/delete_advance/<int:adv_id>')
def delete_advance(adv_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM advances WHERE id = ?", (adv_id,))
        conn.commit()
        conn.close()
        flash('🗑️ تم حذف السجل بنجاح')
    return redirect('/advances')
@app.route('/documents')
def documents_page():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    today_dt = get_ksa_time().date()
    conn, is_pg = get_db()
    employees = run_query(conn, is_pg, "SELECT emp_id, name FROM employees WHERE emp_id != 'admin' ORDER BY name ASC", fetch='all')
    raw_docs = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, doc_type, doc_number, expiry_date, COALESCE(notes, '') FROM emp_documents ORDER BY expiry_date ASC", fetch='all')
    conn.close()
    
    docs = []
    for d in raw_docs:
        try:
            exp_dt = datetime.strptime(d[5], '%Y-%m-%d').date()
            days_left = (exp_dt - today_dt).days
        except Exception:
            days_left = 999
        if days_left < 0:
            status_label, badge_color = f"🔴 منتهية منذ {abs(days_left)} يوم", "#fee2e2; color:#b91c1c"
        elif days_left <= 30:
            status_label, badge_color = f"🟡 متبقي {days_left} يوم", "#fef3c7; color:#b45309"
        else:
            status_label, badge_color = f"🟢 سارية ({days_left} يوم)", "#dcfce7; color:#15803d"
        docs.append({'id': d[0], 'emp_id': d[1], 'emp_name': d[2], 'doc_type': d[3], 'doc_number': d[4], 'expiry_date': d[5], 'notes': d[6], 'status': status_label, 'style': badge_color})
    return render_template('documents.html', page='documents', employees=employees, docs=docs)

@app.route('/add_document', methods=['POST'])
def add_document():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    emp_id = request.form['emp_id']
    doc_type = request.form['doc_type']
    doc_number = request.form['doc_number'].strip()
    expiry_date = request.form['expiry_date']
    notes = request.form.get('notes', '').strip()
    conn, is_pg = get_db()
    emp_row = run_query(conn, is_pg, "SELECT name FROM employees WHERE emp_id = ?", (emp_id,), fetch='one')
    emp_name = emp_row[0] if emp_row else emp_id
    run_query(conn, is_pg, "INSERT INTO emp_documents (emp_id, emp_name, doc_type, doc_number, expiry_date, notes) VALUES (?, ?, ?, ?, ?, ?)",
              (emp_id, emp_name, doc_type, doc_number, expiry_date, notes))
    conn.commit()
    conn.close()
    flash('✅ تم تسجيل الوثيقة وتفعيل متابعة تاريخ الانتهاء!')
    return redirect('/documents')

@app.route('/delete_document/<int:doc_id>')
def delete_document(doc_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM emp_documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        flash('🗑️ تم حذف الوثيقة')
    return redirect('/documents')
@app.route('/evaluations')
def evaluations_page():
    if session.get('role') not in ('admin', 'supervisor'):
        return redirect('/dashboard')
    month = request.args.get('month', get_ksa_time().strftime('%Y-%m'))
    conn, is_pg = get_db()
    if session['role'] == 'supervisor' and session.get('assigned_branch') != 'جميع الفروع':
        employees = run_query(conn, is_pg, "SELECT emp_id, name, department FROM employees WHERE emp_id != 'admin' AND assigned_branch = ? ORDER BY name ASC", (session['assigned_branch'],), fetch='all')
    else:
        employees = run_query(conn, is_pg, "SELECT emp_id, name, department FROM employees WHERE emp_id != 'admin' ORDER BY name ASC", fetch='all')
    evals = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, eval_month, score, bonus, COALESCE(notes, '') FROM evaluations WHERE eval_month = ? ORDER BY id DESC", (month,), fetch='all')
    conn.close()
    return render_template('evaluations.html', page='evaluations', month=month, employees=employees, evals=evals)

@app.route('/save_evaluation', methods=['POST'])
def save_evaluation():
    if session.get('role') not in ('admin', 'supervisor'):
        return redirect('/dashboard')
    emp_id = request.form['emp_id']
    eval_month = request.form['eval_month']
    score = int(request.form['score'])
    bonus = float(request.form.get('bonus') or 0)
    notes = request.form.get('notes', '').strip()
    conn, is_pg = get_db()
    emp_row = run_query(conn, is_pg, "SELECT name FROM employees WHERE emp_id = ?", (emp_id,), fetch='one')
    emp_name = emp_row[0] if emp_row else emp_id
    run_query(conn, is_pg, "DELETE FROM evaluations WHERE emp_id = ? AND eval_month = ?", (emp_id, eval_month))
    run_query(conn, is_pg, "INSERT INTO evaluations (emp_id, emp_name, eval_month, score, bonus, notes) VALUES (?, ?, ?, ?, ?, ?)",
              (emp_id, emp_name, eval_month, score, bonus, notes))
    conn.commit()
    conn.close()
    flash(f'✅ تم حفظ تقييم ومكافأة ({emp_name}) لشهر {eval_month} بنجاح!')
    return redirect(f'/evaluations?month={eval_month}')


@app.route('/shifts')
def shifts_page():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    shifts = run_query(conn, is_pg, "SELECT id, name, shift_type, start1, end1, COALESCE(start2, ''), COALESCE(end2, ''), grace_period FROM shifts ORDER BY id ASC", fetch='all')
    conn.close()
    return render_template('shifts.html', page='shifts', shifts=shifts)

@app.route('/add_shift', methods=['POST'])
def add_shift():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    try:
        run_query(conn, is_pg, "INSERT INTO shifts (name, shift_type, start1, end1, start2, end2, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (request.form['name'].strip(), request.form['shift_type'], request.form['start1'], request.form['end1'],
                   request.form.get('start2', ''), request.form.get('end2', ''), int(request.form['grace_period'])))
        conn.commit()
        flash('✅ تم إضافة الوردية بنجاح!')
    except Exception:
        conn.rollback()
        flash('❌ خطأ: اسم الوردية مسجل مسبقاً!')
    conn.close()
    return redirect('/shifts')

@app.route('/edit_shift/<int:s_id>', methods=['POST'])
def edit_shift(s_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE shifts SET name=?, shift_type=?, start1=?, end1=?, start2=?, end2=?, grace_period=? WHERE id=?",
              (request.form['name'].strip(), request.form['shift_type'], request.form['start1'], request.form['end1'],
               request.form.get('start2', ''), request.form.get('end2', ''), int(request.form['grace_period']), s_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الوردية بنجاح!')
    return redirect('/shifts')

@app.route('/delete_shift/<int:s_id>')
def delete_shift(s_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM shifts WHERE id = ?", (s_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الوردية')
    return redirect('/shifts')

@app.route('/leaves')
def leaves_page():
    if 'emp_id' not in session:
        return redirect('/')
    today = get_ksa_time().strftime('%Y-%m-%d')
    conn, is_pg = get_db()
    if session['role'] == 'admin':
        leaves = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, req_type, req_date, duration_text, reason, status FROM leave_requests ORDER BY id DESC", fetch='all')
    else:
        leaves = run_query(conn, is_pg, "SELECT id, emp_id, emp_name, req_type, req_date, duration_text, reason, status FROM leave_requests WHERE emp_id = ? ORDER BY id DESC", (session['emp_id'],), fetch='all')
    conn.close()
    return render_template('leaves.html', page='leaves', now_date=today, leaves=leaves)

@app.route('/employees')
def employees_page():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    employees = run_query(conn, is_pg, "SELECT emp_id, name, department, job_title, assigned_branch, COALESCE(assigned_shift, 'الوردية الصباحية'), COALESCE(base_salary, 3000), role FROM employees ORDER BY id ASC", fetch='all')
    branches = run_query(conn, is_pg, "SELECT id, name FROM branches", fetch='all')
    shifts = run_query(conn, is_pg, "SELECT id, name FROM shifts ORDER BY id ASC", fetch='all')
    conn.close()
    return render_template('employees.html', page='employees', employees=employees, branches=branches, shifts=shifts)

@app.route('/branches')
def branches_page():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius FROM branches ORDER BY id ASC", fetch='all')
    conn.close()
    return render_template('branches.html', page='branches', branches=branches)
@app.route('/action/<type>', methods=['POST'])
def action(type):
    if 'emp_id' not in session:
        return redirect('/')
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    if not lat or not lon:
        flash('⚠️ يجب السماح للمتصفح بالوصول إلى موقعك الجغرافي (GPS)!')
        return redirect('/dashboard')
        
    conn, is_pg = get_db()
    emp_data = run_query(conn, is_pg, "SELECT assigned_branch, COALESCE(assigned_shift, 'الوردية الصباحية') FROM employees WHERE emp_id = ?", (session['emp_id'],), fetch='one')
    assigned = emp_data[0] if emp_data else 'جميع الفروع'
    shift_name = emp_data[1] if emp_data else 'الوردية الصباحية'
    
    shift_info = run_query(conn, is_pg, "SELECT shift_type, start1, end1, COALESCE(start2, ''), COALESCE(end2, ''), grace_period FROM shifts WHERE name = ?", (shift_name,), fetch='one')
    if not shift_info:
        shift_info = ('single', '08:00', '16:00', '', '', 15)
    s_type, s_start1, s_end1, s_start2, s_end2, s_grace = shift_info

    if assigned == 'جميع الفروع':
        branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius FROM branches", fetch='all')
    else:
        branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius FROM branches WHERE name = ?", (assigned,), fetch='all')
        
    if not branches:
        conn.close()
        flash(f'⚠️ الفرع المخصص لك ({assigned}) غير مسجل في قائمة الفروع.')
        return redirect('/dashboard')

    matched_branch = None
    min_distance = float('inf')
    for b in branches:
        dist = calculate_distance(b[2], b[3], float(lat), float(lon))
        if dist < min_distance:
            min_distance = dist
        if dist <= b[4]:
            matched_branch = b
            break
            
    if not matched_branch:
        conn.close()
        flash(f'❌ عذراً، أنت خارج نطاق مقر عملك ({assigned})! المسافة الحالية {int(min_distance)} متر.')
        return redirect('/dashboard')

    now = get_ksa_time()
    today, t_str = now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S')
    open_rec = run_query(conn, is_pg, "SELECT id, check_in, branch_name FROM attendance WHERE emp_id = ? AND check_out IS NULL ORDER BY id DESC LIMIT 1", (session['emp_id'],), fetch='one')
    done_today = run_query(conn, is_pg, "SELECT COUNT(*) FROM attendance WHERE emp_id = ? AND date = ? AND check_out IS NOT NULL", (session['emp_id'], today), fetch='one')[0]
    max_sessions = 2 if s_type == 'split' else 1
    
    if type == 'in' and not open_rec and done_today < max_sessions:
        if s_type == 'flexible':
            late_mins = 0
            late_txt = "🕒 دوام مرن (منضبط)"
        else:
            target_start = s_start2 if (s_type == 'split' and done_today == 1 and s_start2) else s_start1
            now_mins = time_to_mins(t_str)
            start_mins = time_to_mins(target_start)
            diff_mins = now_mins - start_mins
            if diff_mins < -720:
                diff_mins += 1440
            late_mins = diff_mins if diff_mins > int(s_grace) else 0
            late_txt = f"⚠️ تأخير: {format_mins(late_mins)}" if late_mins > 0 else "✅ منضبط"
        
        run_query(conn, is_pg, "INSERT INTO attendance (emp_id, branch_name, date, check_in, late_minutes, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
                  (session['emp_id'], matched_branch[1], today, t_str, late_mins, request.remote_addr))
        flash(f'✅ تم تسجيل حضورك ({shift_name}) في ({matched_branch[1]}) الساعة {t_str} | {late_txt}')
        send_telegram(f"🟢 تسجيل حضور ({shift_name})\nالموظف: {session['name']} ({session['emp_id']})\nالفرع: {matched_branch[1]}\nالوقت: {t_str}\nالحالة: {late_txt}")
        
    elif type == 'out' and open_rec:
        w_mins = worked_span_mins(open_rec[1], t_str)
        dur_txt = format_mins(w_mins)
        if s_type == 'split' and s_start2 and s_end2:
            req_mins = span_mins(s_start1, s_end1) if done_today == 0 else span_mins(s_start2, s_end2)
        else:
            req_mins = span_mins(s_start1, s_end1)
        ot_mins = (w_mins - req_mins) if w_mins > req_mins else 0
        
        run_query(conn, is_pg, "UPDATE attendance SET check_out = ?, work_hours = ?, overtime_minutes = ? WHERE id = ?",
                  (t_str, dur_txt, ot_mins, open_rec[0]))
        ot_txt = f" | ⭐ إضافي: {format_mins(ot_mins)}" if ot_mins > 0 else ""
        flash(f'🚪 تم تسجيل انصرافك من ({open_rec[2]}) الساعة {t_str} | ساعات العمل: {dur_txt}{ot_txt}')
        send_telegram(f"🔴 تسجيل انصراف ({shift_name})\nالموظف: {session['name']} ({session['emp_id']})\nالفرع: {open_rec[2]}\nالوقت: {t_str}\nساعات العمل: {dur_txt}{ot_txt}")
        
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/add_manual_attendance', methods=['POST'])
def add_manual_attendance():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    emp_id = request.form['emp_id']
    branch = request.form['branch_name']
    att_date = request.form['date']
    c_in = request.form['check_in']
    c_out = request.form.get('check_out', '').strip()
    late_m = int(request.form.get('late_minutes') or 0)
    ot_m = int(request.form.get('overtime_minutes') or 0)
    work_h = format_mins(worked_span_mins(c_in, c_out)) if c_out else 'قيد العمل...'
    
    conn, is_pg = get_db()
    run_query(conn, is_pg, "INSERT INTO attendance (emp_id, branch_name, date, check_in, check_out, work_hours, late_minutes, overtime_minutes, ip_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'admin_manual')",
              (emp_id, branch, att_date, c_in, c_out if c_out else None, work_h, late_m, ot_m))
    conn.commit()
    conn.close()
    flash('✅ تم إضافة سجل الحضور يدوياً بنجاح!')
    return redirect('/dashboard')

@app.route('/edit_attendance/<int:att_id>', methods=['POST'])
def edit_attendance(att_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    c_in = request.form['check_in'].strip()
    c_out = request.form['check_out'].strip()
    late_m = int(request.form.get('late_minutes') or 0)
    ot_m = int(request.form.get('overtime_minutes') or 0)
    work_h = format_mins(worked_span_mins(c_in, c_out)) if (c_out and ':' in c_out) else ('لم يسجل' if c_out == 'لم يسجل' else 'قيد العمل...')
    
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE attendance SET check_in=?, check_out=?, work_hours=?, late_minutes=?, overtime_minutes=? WHERE id=?",
              (c_in, c_out if c_out else None, work_h, late_m, ot_m, att_id))
    conn.commit()
    conn.close()
    flash('✅ تم تعديل سجل الحضور بنجاح!')
    return redirect('/dashboard')

@app.route('/delete_attendance/<int:att_id>')
def delete_attendance(att_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM attendance WHERE id = ?", (att_id,))
        conn.commit()
        conn.close()
        flash('🗑️ تم حذف السجل بنجاح!')
    return redirect('/dashboard')

@app.route('/submit_leave', methods=['POST'])
def submit_leave():
    if 'emp_id' not in session:
        return redirect('/')
    req_type = request.form['req_type']
    req_date = request.form['req_date']
    duration_text = request.form['duration_text'].strip()
    reason = request.form['reason'].strip()
    now_str = get_ksa_time().strftime('%Y-%m-%d %H:%M')
    
    conn, is_pg = get_db()
    run_query(conn, is_pg, "INSERT INTO leave_requests (emp_id, emp_name, req_type, req_date, duration_text, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'قيد المراجعة', ?)",
              (session['emp_id'], session['name'], req_type, req_date, duration_text, reason, now_str))
    conn.commit()
    conn.close()
    
    flash('✅ تم إرسال طلبك للإدارة بنجاح!')
    send_telegram(f"📩 طلب جديد ({req_type})\nالموظف: {session['name']} ({session['emp_id']})\nالتاريخ: {req_date}\nالمدة: {duration_text}\nالسبب: {reason}")
    return redirect('/leaves')

@app.route('/handle_leave/<int:req_id>/<decision>')
def handle_leave(req_id, decision):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    status = 'مقبول ✅' if decision == 'approve' else 'مرفوض ❌'
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE leave_requests SET status = ? WHERE id = ?", (status, req_id))
    conn.commit()
    conn.close()
    flash(f'تم تحديث حالة الطلب إلى: {status}')
    return redirect('/leaves')

@app.route('/delete_leave/<int:req_id>')
def delete_leave(req_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM leave_requests WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()
        flash('🗑️ تم حذف الطلب بنجاح')
    return redirect('/leaves')

@app.route('/add_branch', methods=['POST'])
def add_branch():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "INSERT INTO branches (name, lat, lon, radius) VALUES (?, ?, ?, ?)",
              (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius'])))
    conn.commit()
    conn.close()
    flash('✅ تم إضافة الفرع بنجاح!')
    return redirect('/branches')

@app.route('/edit_branch/<int:b_id>', methods=['POST'])
def edit_branch(b_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE branches SET name=?, lat=?, lon=?, radius=? WHERE id=?",
              (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius']), b_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الفرع بنجاح!')
    return redirect('/branches')

@app.route('/delete_branch/<int:b_id>')
def delete_branch(b_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM branches WHERE id = ?", (b_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الفرع')
    return redirect('/branches')

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    try:
        role = request.form.get('role', 'employee')
        run_query(conn, is_pg, "INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, assigned_shift, base_salary, password, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (request.form['emp_id'].strip(), request.form['name'].strip(), request.form['department'].strip(), request.form['job_title'].strip(), request.form['assigned_branch'], request.form['assigned_shift'], float(request.form.get('base_salary') or 3000), generate_password_hash(request.form['password'].strip()), role))
        conn.commit()
        flash('✅ تم إضافة الموظف وربطه بالفرع والوردية والراتب بنجاح!')
    except Exception:
        conn.rollback()
        flash('❌ خطأ: الرقم الوظيفي مسجل مسبقاً!')
    conn.close()
    return redirect('/employees')

@app.route('/edit_employee/<emp_id>', methods=['POST'])
def edit_employee(emp_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    name, dept, title = request.form['name'].strip(), request.form['department'].strip(), request.form['job_title'].strip()
    branch, shift = request.form['assigned_branch'], request.form['assigned_shift']
    salary = float(request.form.get('base_salary') or 0)
    role = 'admin' if emp_id == 'admin' else request.form.get('role', 'employee')
    new_pass = request.form.get('password', '').strip()
    if new_pass:
        run_query(conn, is_pg, "UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=?, assigned_shift=?, base_salary=?, role=?, password=? WHERE emp_id=?",
                  (name, dept, title, branch, shift, salary, role, generate_password_hash(new_pass), emp_id))
    else:
        run_query(conn, is_pg, "UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=?, assigned_shift=?, base_salary=?, role=? WHERE emp_id=?",
                  (name, dept, title, branch, shift, salary, role, emp_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الموظف بنجاح!')
    return redirect('/employees')


@app.route('/delete_emp/<emp_id>')
def delete_emp(emp_id):
    if session.get('role') == 'admin' and emp_id != 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM employees WHERE emp_id = ?", (emp_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الموظف')
    return redirect('/employees')

@app.route('/export_csv')
def export_csv():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    emp_filter, start_date, end_date = request.args.get('emp_id', ''), request.args.get('start_date', ''), request.args.get('end_date', '')
    query = "SELECT a.emp_id, e.name, e.department, a.branch_name, a.date, a.check_in, a.check_out, a.work_hours, COALESCE(a.late_minutes, 0), COALESCE(a.overtime_minutes, 0) FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE 1=1"
    params = []
    if emp_filter:
        query += " AND a.emp_id = ?"
        params.append(emp_filter)
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
    query += " ORDER BY a.id DESC"
    conn, is_pg = get_db()
    raw_rows = run_query(conn, is_pg, query, tuple(params), fetch='all')
    conn.close()
    
    formatted_rows = [(r, r, r, r, r, r, r, r, format_mins(r), format_mins(r)) for r in raw_rows]
    out = io.StringIO()
    out.write('\ufeff')
    w = csv.writer(out, delimiter=';')
    w.writerow(['الرقم الوظيفي', 'الاسم', 'القسم', 'الفرع', 'التاريخ', 'الحضور', 'الانصراف', 'ساعات العمل', 'التأخير', 'العمل الإضافي'])
    w.writerows(formatted_rows)
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=attendance_report.csv"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
     app.run(host='0.0.0.0', port=5000, debug=False)
