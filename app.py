from flask import Flask, render_template, request, redirect, session, flash, Response
import sqlite3, csv, io, math
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'wahid_hr_pro_system_v2_2026'
KSA_TZ = timezone(timedelta(hours=3))

def get_ksa_time():
    return datetime.now(KSA_TZ)

def init_db():
    conn = sqlite3.connect('attendance.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY, emp_id TEXT UNIQUE, name TEXT, department TEXT, job_title TEXT, assigned_branch TEXT, password TEXT, role TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL, radius INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, emp_id TEXT, branch_name TEXT, date TEXT, check_in TEXT, check_out TEXT, work_hours TEXT, ip_address TEXT)')
    
    try: c.execute("ALTER TABLE employees ADD COLUMN assigned_branch TEXT DEFAULT 'جميع الفروع'")
    except: pass
    try: c.execute("ALTER TABLE attendance ADD COLUMN branch_name TEXT DEFAULT 'الفرع الرئيسي'")
    except: pass

    if c.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 0:
        c.execute("INSERT INTO branches (name, lat, lon, radius) VALUES (?, ?, ?, ?)", ('الفرع الرئيسي', 16.9688, 42.8325, 200))

    if c.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
        users = [
            ('admin', 'وحيد - مدير الموارد البشرية', 'الإدارة العليا', 'مدير النظام', 'جميع الفروع', generate_password_hash('123456'), 'admin'),
            ('1001', 'أحمد محمد العتيبي', 'الأمن السيبراني', 'محلل أمن معلومات', 'الفرع الرئيسي', generate_password_hash('123456'), 'employee')
        ]
        c.executemany("INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, password, role) VALUES (?, ?, ?, ?, ?, ?, ?)", users)
        
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

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'emp_id' in session:
        return redirect('/dashboard')
    if request.method == 'POST':
        conn = sqlite3.connect('attendance.db')
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT * FROM employees WHERE emp_id = ?", (request.form['emp_id'].strip(),)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], request.form['password'].strip()):
            session['emp_id'] = user['emp_id']
            session['name'] = user['name']
            session['job_title'] = user['job_title']
            session['assigned_branch'] = user['assigned_branch']
            session['role'] = user['role']
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
    
    conn = sqlite3.connect('attendance.db')
    c = conn.cursor()
    today_rec = c.execute("SELECT * FROM attendance WHERE emp_id = ? AND date = ?", (session['emp_id'], today)).fetchone()
    
    query = "SELECT a.emp_id, e.name, e.department, a.branch_name, a.date, a.check_in, a.check_out, a.work_hours FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE 1=1"
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
    records = c.execute(query, params).fetchall()
    
    stats, employees, branches = {}, [], []
    if session['role'] == 'admin':
        employees = c.execute("SELECT emp_id, name, department, job_title, assigned_branch, role FROM employees").fetchall()
        branches = c.execute("SELECT id, name, lat, lon, radius FROM branches").fetchall()
        present = c.execute("SELECT COUNT(*) FROM attendance WHERE date = ?", (today,)).fetchone()[0]
        active = c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND check_out IS NULL", (today,)).fetchone()[0]
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
        flash('⚠️ يجب السماح للمتصفح بالوصول إلى موقعك الجغرافي (GPS) لتسجيل الحضور والانصراف!', 'danger')
        return redirect('/dashboard')
        
    conn = sqlite3.connect('attendance.db')
    conn.row_factory = sqlite3.Row
    emp_data = conn.execute("SELECT assigned_branch FROM employees WHERE emp_id = ?", (session['emp_id'],)).fetchone()
    assigned = emp_data['assigned_branch'] if emp_data else 'جميع الفروع'
    
    if assigned == 'جميع الفروع':
        branches = conn.execute("SELECT * FROM branches").fetchall()
    else:
        branches = conn.execute("SELECT * FROM branches WHERE name = ?", (assigned,)).fetchall()
        
    if not branches:
        conn.close()
        flash(f'⚠️ الفرع المخصص لك ({assigned}) غير مسجل في قائمة الفروع، تواصل مع الإدارة.', 'danger')
        return redirect('/dashboard')

    matched_branch = None
    min_distance = float('inf')
    for b in branches:
        dist = calculate_distance(b['lat'], b['lon'], float(lat), float(lon))
        if dist < min_distance:
            min_distance = dist
        if dist <= b['radius']:
            matched_branch = b['name']
            break
            
    if not matched_branch:
        conn.close()
        if assigned == 'جميع الفروع':
            flash(f'❌ عذراً، أنت خارج نطاق جميع فروع الشركة! أقرب فرع يبعد عنك {int(min_distance)} متر.', 'danger')
        else:
            flash(f'❌ عذراً، يجب أن تكون متواجداً في مقر عملك المخصص ({assigned})! المسافة الحالية بينك وبينه {int(min_distance)} متر.', 'danger')
        return redirect('/dashboard')

    now = get_ksa_time()
    today, t_str = now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S')
    rec = conn.execute("SELECT * FROM attendance WHERE emp_id = ? AND date = ?", (session['emp_id'], today)).fetchone()
    
    if type == 'in' and not rec:
        conn.execute("INSERT INTO attendance (emp_id, branch_name, date, check_in, ip_address) VALUES (?, ?, ?, ?, ?)",
                     (session['emp_id'], matched_branch, today, t_str, request.remote_addr))
        flash(f'✅ تم تسجيل حضورك في ({matched_branch}) الساعة {t_str}', 'success')
    elif type == 'out' and rec and not rec['check_out']:
        dur = calculate_duration(rec['check_in'], t_str)
        conn.execute("UPDATE attendance SET check_out = ?, work_hours = ? WHERE id = ?", (t_str, dur, rec['id']))
        flash(f'🚪 تم تسجيل انصرافك من ({matched_branch}) الساعة {t_str} | ساعات العمل: {dur}', 'info')
        
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/add_branch', methods=['POST'])
def add_branch():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn = sqlite3.connect('attendance.db')
    conn.execute("INSERT INTO branches (name, lat, lon, radius) VALUES (?, ?, ?, ?)",
                 (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius'])))
    conn.commit()
    conn.close()
    flash('✅ تم إضافة الفرع الجديد بنجاح!', 'success')
    return redirect('/dashboard')

@app.route('/edit_branch/<int:b_id>', methods=['POST'])
def edit_branch(b_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn = sqlite3.connect('attendance.db')
    conn.execute("UPDATE branches SET name=?, lat=?, lon=?, radius=? WHERE id=?",
                 (request.form['name'].strip(), float(request.form['lat']), float(request.form['lon']), int(request.form['radius']), b_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الفرع بنجاح!', 'success')
    return redirect('/dashboard')

@app.route('/delete_branch/<int:b_id>')
def delete_branch(b_id):
    if session.get('role') == 'admin':
        conn = sqlite3.connect('attendance.db')
        conn.execute("DELETE FROM branches WHERE id = ?", (b_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الفرع', 'warning')
    return redirect('/dashboard')

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn = sqlite3.connect('attendance.db')
    try:
        conn.execute("INSERT INTO employees (emp_id, name, department, job_title, assigned_branch, password, role) VALUES (?, ?, ?, ?, ?, ?, 'employee')",
                     (request.form['emp_id'].strip(), request.form['name'].strip(), request.form['department'].strip(), request.form['job_title'].strip(), request.form['assigned_branch'], generate_password_hash(request.form['password'].strip())))
        conn.commit()
        flash('✅ تم إضافة الموظف وربطه بفرعه بنجاح!', 'success')
    except sqlite3.IntegrityError:
        flash('❌ خطأ: الرقم الوظيفي مسجل مسبقاً!', 'danger')
    conn.close()
    return redirect('/dashboard')

@app.route('/edit_employee/<emp_id>', methods=['POST'])
def edit_employee(emp_id):
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    conn = sqlite3.connect('attendance.db')
    name = request.form['name'].strip()
    dept = request.form['department'].strip()
    title = request.form['job_title'].strip()
    branch = request.form['assigned_branch']
    new_pass = request.form.get('password', '').strip()
    
    if new_pass:
        conn.execute("UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=?, password=? WHERE emp_id=?",
                     (name, dept, title, branch, generate_password_hash(new_pass), emp_id))
    else:
        conn.execute("UPDATE employees SET name=?, department=?, job_title=?, assigned_branch=? WHERE emp_id=?",
                     (name, dept, title, branch, emp_id))
    conn.commit()
    conn.close()
    flash('✅ تم حفظ تعديلات الموظف بنجاح!', 'success')
    return redirect('/dashboard')

@app.route('/delete_emp/<emp_id>')
def delete_emp(emp_id):
    if session.get('role') == 'admin' and emp_id != 'admin':
        conn = sqlite3.connect('attendance.db')
        conn.execute("DELETE FROM employees WHERE emp_id = ?", (emp_id,))
        conn.commit()
        conn.close()
        flash('تم حذف الموظف', 'warning')
    return redirect('/dashboard')

@app.route('/export_csv')
def export_csv():
    if session.get('role') != 'admin':
        return redirect('/dashboard')
    emp_filter = request.args.get('emp_id', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = "SELECT a.emp_id, e.name, e.department, a.branch_name, a.date, a.check_in, a.check_out, a.work_hours FROM attendance a JOIN employees e ON a.emp_id = e.emp_id WHERE 1=1"
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
    
    conn = sqlite3.connect('attendance.db')
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    out = io.StringIO()
    out.write('\ufeff')
    w = csv.writer(out, delimiter=';')
    w.writerow(['الرقم الوظيفي', 'الاسم', 'القسم', 'الفرع', 'التاريخ', 'الحضور', 'الانصراف', 'ساعات العمل'])
    w.writerows(rows)
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=attendance_report.csv"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
