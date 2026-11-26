from flask import Flask, render_template, request, redirect, session, flash, Response
import os, sqlite3, csv, io, math
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'wahid_hr_pro_system_v2_2026'
KSA_TZ = timezone(timedelta(hours=3))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

def get_ksa_time():
    return datetime.now(KSA_TZ)

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
    run_query(conn, is_pg, f'CREATE TABLE IF NOT EXISTS employees (id {pk}, emp_id TEXT UNIQUE, name TEXT, department TEXT, job_title TEXT, assigned_branch TEXT, password TEXT, role TEXT)')
    run_query(conn, is_pg, f"CREATE TABLE IF NOT EXISTS branches (id {pk}, name TEXT, lat REAL, lon REAL, radius INTEGER, start_time TEXT DEFAULT '08:00', end_time TEXT DEFAULT '16:00', grace_period INTEGER DEFAULT 15)")
    run_query(conn, is_pg, f'CREATE TABLE IF NOT EXISTS attendance (id {pk}, emp_id TEXT, branch_name TEXT, date TEXT, check_in TEXT, check_out TEXT, work_hours TEXT, late_minutes INTEGER DEFAULT 0, overtime_minutes INTEGER DEFAULT 0, ip_address TEXT)')
    conn.commit()
run_query(conn, is_pg, "UPDATE attendance SET overtime_minutes = 0 WHERE emp_id = '1001' AND date = '2026-11-26'
    safe_alter(conn, is_pg, "ALTER TABLE branches ADD COLUMN start_time TEXT DEFAULT '08:00'")
    safe_alter(conn, is_pg, "ALTER TABLE branches ADD COLUMN end_time TEXT DEFAULT '16:00'")
    safe_alter(conn, is_pg, "ALTER TABLE branches ADD COLUMN grace_period INTEGER DEFAULT 15")
    safe_alter(conn, is_pg, "ALTER TABLE attendance ADD COLUMN late_minutes INTEGER DEFAULT 0")
    safe_alter(conn, is_pg, "ALTER TABLE attendance ADD COLUMN overtime_minutes INTEGER DEFAULT 0")

    b_count = run_query(conn, is_pg, "SELECT COUNT(*) FROM branches", fetch='one')[0]
    if b_count == 0:
        run_query(conn, is_pg, "INSERT INTO branches (name, lat, lon, radius, start_time, end_time, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  ('الفرع الرئيسي', 16.9688, 42.8325, 200, '08:00', '16:00', 15))

    e_count = run_query(conn, is_pg, "SELECT COUNT(*) FROM employees", fetch='one')[0]
    if e_count == 0:
        run_query(conn, is_pg, "INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, password, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  ('admin', 'وحيد - مدير الموارد البشرية', 'الإدارة العليا', 'مدير النظام', 'جميع الفروع', generate_password_hash('123456'), 'admin'))
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

def calculate_duration(in_str, out_str):
    diff = datetime.strptime(out_str, '%H:%M:%S') - datetime.strptime(in_str, '%H:%M:%S')
    sec = max(0, int(diff.total_seconds()))
    return f"{sec // 3600} س و {(sec % 3600) // 60} د"

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
    today_rec = run_query(conn, is_pg, "SELECT id, emp_id, branch_name, date, check_in, check_out, work_hours FROM attendance WHERE emp_id = ? AND date = ?", (session['emp_id'], today), fetch='one')
    
    query = "SELECT a.emp_id, e.name, e.department, a.branch_name, a.date, a.check_in, a.check_out, a.work_hours, COALESCE(a.late_minutes, 0), COALESCE(a.overtime_minutes, 0) FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE 1=1"
    params = []
    if session['role'] != 'admin':
        query += " AND a.emp_id = ?"
        params.append(session['emp_id'])
    elif emp_filter:
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
    
    records = []
    for r in raw_records:
        records.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], format_mins(r[8]), r[9], format_mins(r[9])))
    
    stats, employees, branches = {}, [], []
    if session['role'] == 'admin':
        employees = run_query(conn, is_pg, "SELECT emp_id, name, department, job_title, assigned_branch, role FROM employees", fetch='all')
        branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius, COALESCE(start_time, '08:00'), COALESCE(end_time, '16:00'), COALESCE(grace_period, 15) FROM branches", fetch='all')
        present = run_query(conn, is_pg, "SELECT COUNT(*) FROM attendance WHERE date = ?", (today,), fetch='one')[0]
        active = run_query(conn, is_pg, "SELECT COUNT(*) FROM attendance WHERE date = ? AND check_out IS NULL", (today,), fetch='one')[0]
        stats = {'total_emp': len(employees), 'present_today': present, 'active_now': active}
    conn.close()
    return render_template('dashboard.html', now_time=now.strftime('%H:%M:%S'), now_date=today, today_rec=today_rec, records=records, stats=stats, employees=employees, branches=branches, emp_filter=emp_filter, start_date=start_date, end_date=end_date)

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
    emp_data = run_query(conn, is_pg, "SELECT assigned_branch FROM employees WHERE emp_id = ?", (session['emp_id'],), fetch='one')
    assigned = emp_data[0] if emp_data else 'جميع الفروع'
    
    if assigned == 'جميع الفروع':
        branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius, COALESCE(start_time, '08:00'), COALESCE(end_time, '16:00'), COALESCE(grace_period, 15) FROM branches", fetch='all')
    else:
        branches = run_query(conn, is_pg, "SELECT id, name, lat, lon, radius, COALESCE(start_time, '08:00'), COALESCE(end_time, '16:00'), COALESCE(grace_period, 15) FROM branches WHERE name = ?", (assigned,), fetch='all')
        
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
    rec = run_query(conn, is_pg, "SELECT id, check_in, check_out, branch_name FROM attendance WHERE emp_id = ? AND date = ?", (session['emp_id'], today), fetch='one')
    
    if type == 'in' and not rec:
        b_name, b_start, b_grace = matched_branch[1], matched_branch[5], int(matched_branch[7])
        in_dt = datetime.strptime(t_str, '%H:%M:%S')
        start_dt = datetime.strptime(b_start, '%H:%M')
        allowed_dt = start_dt + timedelta(minutes=b_grace)
        late_mins = int((in_dt - start_dt).total_seconds() // 60) if in_dt > allowed_dt else 0
        
        run_query(conn, is_pg, "INSERT INTO attendance (emp_id, branch_name, date, check_in, late_minutes, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
                  (session['emp_id'], b_name, today, t_str, late_mins, request.remote_addr))
        late_msg = f" | ⚠️ تأخير: {format_mins(late_mins)}" if late_mins > 0 else " | ✅ حضور منضبط"
        flash(f'✅ تم تسجيل حضورك في ({b_name}) الساعة {t_str}{late_msg}')
        
    elif type == 'out' and rec and not rec[2]:
        dur = calculate_duration(rec[1], t_str)
        b_info = run_query(conn, is_pg, "SELECT COALESCE(start_time, '08:00'), COALESCE(end_time, '16:00') FROM branches WHERE name = ?", (rec[3],), fetch='one')
        b_start = b_info[0] if b_info else matched_branch[5]
        b_end = b_info[1] if b_info else matched_branch[6]
        
        in_dt = datetime.strptime(rec[1], '%H:%M:%S')
        out_dt = datetime.strptime(t_str, '%H:%M:%S')
        worked_mins = max(0, int((out_dt - in_dt).total_seconds() // 60))
        
        start_dt = datetime.strptime(b_start, '%H:%M')
        end_dt = datetime.strptime(b_end, '%H:%M')
        required_mins = max(0, int((end_dt - start_dt).total_seconds() // 60))
        
        ot_mins = max(0, worked_mins - required_mins) if worked_mins > required_mins else 0
        
        run_query(conn, is_pg, "UPDATE attendance SET check_out = ?, work_hours = ?, overtime_minutes = ? WHERE id = ?",
                  (t_str, dur, ot_mins, rec[0]))
        ot_msg = f" | ⭐ عمل إضافي: {format_mins(ot_mins)}" if ot_mins > 0 else ""
        flash(f'🚪 تم تسجيل انصرافك من ({rec[3]}) الساعة {t_str} | ساعات العمل: {dur}{ot_msg}')
        
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/add_branch', methods=['POST'])
def add_branch():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "INSERT INTO branches (name, lat, lon, radius, start_time, end_time, grace_period) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius']),
               request.form['start_time'], request.form['end_time'], int(request.form['grace_period'])))
    conn.commit()
    conn.close()
    flash('✅ تم إضافة الفرع ومواعيد دوامه بنجاح!')
    return redirect('/dashboard')

@app.route('/edit_branch/<int:b_id>', methods=['POST'])
def edit_branch(b_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    run_query(conn, is_pg, "UPDATE branches SET name=?, lat=?, lon=?, radius=?, start_time=?, end_time=?, grace_period=? WHERE id=?",
              (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius']),
               request.form['start_time'], request.form['end_time'], int(request.form['grace_period']), b_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الفرع ومواعيد الدوام بنجاح!')
    return redirect('/dashboard')

@app.route('/delete_branch/<int:b_id>')
def delete_branch(b_id):
    if session.get('role') == 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM branches WHERE id = ?", (b_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الفرع')
    return redirect('/dashboard')

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    try:
        run_query(conn, is_pg, "INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, password, role) VALUES (?, ?, ?, ?, ?, ?, 'employee')",
                  (request.form['emp_id'].strip(), request.form['name'].strip(), request.form['department'].strip(), request.form['job_title'].strip(), request.form['assigned_branch'], generate_password_hash(request.form['password'].strip())))
        conn.commit()
        flash('✅ تم إضافة الموظف وربطه بفرعه بنجاح!')
    except Exception:
        conn.rollback()
        flash('❌ خطأ: الرقم الوظيفي مسجل مسبقاً!')
    conn.close()
    return redirect('/dashboard')

@app.route('/edit_employee/<emp_id>', methods=['POST'])
def edit_employee(emp_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn, is_pg = get_db()
    name, dept, title, branch = request.form['name'].strip(), request.form['department'].strip(), request.form['job_title'].strip(), request.form['assigned_branch']
    new_pass = request.form.get('password', '').strip()
    if new_pass:
        run_query(conn, is_pg, "UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=?, password=? WHERE emp_id=?",
                  (name, dept, title, branch, generate_password_hash(new_pass), emp_id))
    else:
        run_query(conn, is_pg, "UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=? WHERE emp_id=?",
                  (name, dept, title, branch, emp_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الموظف بنجاح!')
    return redirect('/dashboard')

@app.route('/delete_emp/<emp_id>')
def delete_emp(emp_id):
    if session.get('role') == 'admin' and emp_id != 'admin':
        conn, is_pg = get_db()
        run_query(conn, is_pg, "DELETE FROM employees WHERE emp_id = ?", (emp_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الموظف')
    return redirect('/dashboard')

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
    
    formatted_rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], format_mins(r[8]), format_mins(r[9])) for r in raw_rows]
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
