import os
import secrets
import re
from collections import defaultdict, deque
from datetime import datetime, date, time, timedelta
from functools import wraps

import mysql.connector
from mysql.connector import Error, IntegrityError
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

# Render sits behind a trusted reverse proxy. ProxyFix lets Flask see the
# original client IP from the proxy headers for the office-IP allowlist.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "0") == "1"

_secret_key = os.getenv("SECRET_KEY", "").strip()
if not _secret_key:
    if app.config["DEBUG"]:
        _secret_key = secrets.token_hex(32)
    else:
        raise RuntimeError("SECRET_KEY must be set in the production environment.")
app.config["SECRET_KEY"] = _secret_key

app.config["CODE_MINUTES"] = int(os.getenv("ATTENDANCE_CODE_MINUTES", "10"))
app.config["LATE_AFTER"] = os.getenv("LATE_AFTER", "09:30")
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "1" if not app.config["DEBUG"] else "0") == "1"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "None")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.getenv("SESSION_HOURS", "8")))
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(2 * 1024 * 1024)))
_trusted_hosts = [h.strip() for h in os.getenv("TRUSTED_HOSTS", "").split(",") if h.strip()]
if _trusted_hosts:
    app.config["TRUSTED_HOSTS"] = _trusted_hosts

LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "900"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_RATE_MAX_FAILURES", "8"))
_login_failures = defaultdict(deque)

def _client_key(email):
    ip = request.remote_addr or "unknown"
    return f"{ip}|{email}"

def login_rate_limited(email):
    now = datetime.now().timestamp()
    bucket = _login_failures[_client_key(email)]
    while bucket and now - bucket[0] > LOGIN_WINDOW_SECONDS:
        bucket.popleft()
    return len(bucket) >= LOGIN_MAX_FAILURES

def record_login_failure(email):
    now = datetime.now().timestamp()
    bucket = _login_failures[_client_key(email)]
    while bucket and now - bucket[0] > LOGIN_WINDOW_SECONDS:
        bucket.popleft()
    bucket.append(now)

def clear_login_failures(email):
    _login_failures.pop(_client_key(email), None)


def db_config(include_database=True):
    cfg = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
    }
    if include_database:
        cfg["database"] = os.getenv("MYSQL_DB", "startup_labbook")
    return cfg


def get_db():
    return mysql.connector.connect(**db_config())


def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        if commit:
            conn.commit()
            return cur.lastrowid
        if fetchone:
            return cur.fetchone()
        if fetchall:
            return cur.fetchall()
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def execute_many(sql, rows):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.executemany(sql, rows)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def ensure_database():
    """Create the configured database and required tables without destructive DROP statements."""
    conn = None
    cur = None
    db_name = os.getenv("MYSQL_DB", "startup_labbook")
    try:
        server_cfg = db_config(include_database=False)
        conn = mysql.connector.connect(**server_cfg)
        cur = conn.cursor()
        safe_db = "".join(ch for ch in db_name if ch.isalnum() or ch == "_")
        if safe_db != db_name:
            raise RuntimeError("MYSQL_DB contains unsupported characters.")
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{safe_db}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    conn = mysql.connector.connect(**db_config())
    cur = conn.cursor()
    statements = [
        """CREATE TABLE IF NOT EXISTS admins (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            email VARCHAR(190) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_admin_active (active)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS employees (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            employee_code VARCHAR(50) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            email VARCHAR(190) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            designation VARCHAR(120) NOT NULL,
            department VARCHAR(120) NOT NULL,
            phone VARCHAR(30) NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_employee_active (active),
            INDEX idx_employee_department (department),
            INDEX idx_employee_designation (designation)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            attendance_date DATE NOT NULL,
            code CHAR(6) NOT NULL,
            expires_at DATETIME NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_attendance_session_date (attendance_date),
            INDEX idx_attendance_session_expiry (expires_at)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS attendance (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            employee_id INT UNSIGNED NOT NULL,
            attendance_date DATE NOT NULL,
            check_in DATETIME NULL,
            check_out DATETIME NULL,
            status ENUM('Present','Late') NOT NULL DEFAULT 'Present',
            session_id INT UNSIGNED NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_attendance_employee FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            CONSTRAINT fk_attendance_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id)
                ON UPDATE CASCADE ON DELETE SET NULL,
            CONSTRAINT uq_employee_attendance_date UNIQUE (employee_id, attendance_date),
            INDEX idx_attendance_date (attendance_date)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS daily_work (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            employee_id INT UNSIGNED NOT NULL,
            work_date DATE NOT NULL,
            work_title VARCHAR(180) NOT NULL,
            work_description TEXT NOT NULL,
            progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
            status ENUM('Not Started','In Progress','Completed') NOT NULL DEFAULT 'Not Started',
            blockers TEXT NULL,
            tomorrow_plan TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_work_employee FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            CONSTRAINT uq_employee_work_date UNIQUE (employee_id, work_date),
            INDEX idx_work_date (work_date)
        ) ENGINE=InnoDB""",
        """CREATE TABLE IF NOT EXISTS meeting_notes (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            note_date DATE NOT NULL,
            title VARCHAR(180) NOT NULL,
            discussion TEXT NOT NULL,
            decisions TEXT NULL,
            action_items TEXT NULL,
            created_by INT UNSIGNED NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT fk_notes_admin FOREIGN KEY (created_by) REFERENCES admins(id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            INDEX idx_notes_date (note_date)
        ) ENGINE=InnoDB""",
    ]
    try:
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def bootstrap_admin():
    email = os.getenv("DEFAULT_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("DEFAULT_ADMIN_PASSWORD", "")
    name = os.getenv("DEFAULT_ADMIN_NAME", "System Administrator").strip()
    if not email or not password:
        return
    existing = query("SELECT id FROM admins WHERE email=%s", (email,), fetchone=True)
    if not existing:
        query(
            "INSERT INTO admins (name,email,password_hash,active) VALUES (%s,%s,%s,1)",
            (name, email, generate_password_hash(password)),
            commit=True,
        )


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]

app.jinja_env.globals["csrf_token"] = csrf_token


_api_db_initialized = False

@app.before_request
def security_api():
    global _api_db_initialized

    # Set CORS metadata before the IP check so blocked requests still return
    # the proper CORS headers to the Netlify browser client. Without this,
    # the browser reports a generic "Failed to fetch" instead of the actual
    # 403 response.
    origin = request.headers.get("Origin", "").rstrip("/")
    allowed = {x.strip().rstrip("/") for x in os.getenv("CORS_ORIGINS", "https://verbas.in,https://www.verbas.in").split(",") if x.strip()}
    request.cors_origin = origin if origin in allowed else None

    # Optional public-IP allowlist. When ALLOWED_PUBLIC_IPS is set, every
    # application request must come from one of those public IPv4/IPv6
    # addresses. Keep this list limited to the company's office internet
    # public IP(s). Multiple addresses may be comma-separated.
    allowed_ips = {x.strip() for x in os.getenv("ALLOWED_PUBLIC_IPS", "").split(",") if x.strip()}
    if allowed_ips:
        # Render sits behind Cloudflare/load balancers, so request.remote_addr
        # is normally a Render proxy address, not the user's public IP.
        # Render documents CF-Connecting-IP as the real client IP signal.
        client_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if not client_ip:
            forwarded = request.headers.get("X-Forwarded-For", "")
            client_ip = forwarded.split(",", 1)[0].strip() if forwarded else ""
        if not client_ip:
            client_ip = request.remote_addr or ""
        if client_ip not in allowed_ips:
            return jsonify({"ok": False, "message": "Access is allowed only from the authorized office network."}), 403

    if not _api_db_initialized:
        ensure_database()
        bootstrap_admin()
        _api_db_initialized = True
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path not in {"/api/auth/login", "/api/auth/csrf", "/api/auth/admin-reset"}:
        token = request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not token or not expected or not secrets.compare_digest(token, expected):
            return jsonify({"ok": False, "message": "Security token missing or expired."}), 403


@app.after_request
def security_headers(response):
    origin = getattr(request, "cors_origin", None)
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if os.getenv("FORCE_HSTS", "0") == "1" or request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def login_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("admin_login" if role == "admin" else "login"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def format_duration(start, end):
    if not start or not end:
        return "—"
    seconds = int((end - start).total_seconds())
    hours, rem = divmod(max(0, seconds), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"



def api_error(message, status=400):
    return jsonify({"ok": False, "message": message}), status


def api_user(role):
    if session.get("role") != role or not session.get("user_id"):
        return None
    table = "admins" if role == "admin" else "employees"
    return query(f"SELECT * FROM {table} WHERE id=%s AND active=1", (session["user_id"],), fetchone=True)


def json_row(row):
    if not row: return row
    out=dict(row)
    out.pop("password_hash", None)
    for k,v in list(out.items()):
        if hasattr(v,"isoformat"): out[k]=v.isoformat()
    return out

@app.get("/")
def api_root():
    return jsonify({"ok":True,"service":"VERBAS Employee Management API","version":"1.0"})

@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path): return ("",204)

@app.get("/api/health")
def api_health():
    try:
        query("SELECT 1", fetchone=True)
        return jsonify({"ok":True,"service":"verbas-backend","database":"connected"})
    except Exception:
        return api_error("Database unavailable.",503)

@app.get("/api/auth/csrf")
def api_csrf():
    if "_csrf" not in session: session["_csrf"]=secrets.token_urlsafe(32)
    return jsonify({"ok":True,"csrf_token":session["_csrf"]})

@app.post("/api/auth/admin-reset")
def api_admin_reset():
    """One-time emergency admin password reset protected by a Render secret.

    This endpoint is intended to be removed after the administrator password is
    reset. It never accepts or stores a plaintext password in MySQL.
    """
    reset_token = os.getenv("ADMIN_RESET_TOKEN", "")
    reset_email = os.getenv("RESET_ADMIN_EMAIL", "").strip().lower()
    supplied_token = request.headers.get("X-Admin-Reset-Token", "")
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not reset_token or not reset_email:
        return api_error("Admin reset is not configured.", 404)
    if not supplied_token or not secrets.compare_digest(supplied_token, reset_token):
        return api_error("Unauthorized.", 401)
    if email != reset_email:
        return api_error("Invalid reset account.", 400)
    if len(password) < 12:
        return api_error("Password must be at least 12 characters.", 400)

    admin = query("SELECT id FROM admins WHERE email=%s AND active=1", (email,), fetchone=True)
    if not admin:
        return api_error("Admin account not found.", 404)

    query(
        "UPDATE admins SET password_hash=%s WHERE id=%s",
        (generate_password_hash(password), admin["id"]),
        commit=True,
    )
    return jsonify({"ok": True, "message": "Admin password reset successfully. Remove ADMIN_RESET_TOKEN and RESET_ADMIN_EMAIL now."})


@app.post("/api/auth/login")
def api_login():
    data=request.get_json(silent=True) or {}
    email=str(data.get("email","")).strip().lower(); password=str(data.get("password","")); role=str(data.get("role","employee")).lower()
    if role not in {"employee","admin"}: return api_error("Invalid role.")
    if not email or not password: return api_error("Email and password are required.")
    if login_rate_limited(email): return api_error("Too many failed sign-in attempts. Please wait and try again.",429)
    table="admins" if role=="admin" else "employees"
    user=query(f"SELECT * FROM {table} WHERE email=%s AND active=1",(email,),fetchone=True)
    if not user or not check_password_hash(user["password_hash"],password):
        record_login_failure(email); return api_error("Invalid email or password.",401)
    clear_login_failures(email); session.clear(); session.permanent=True
    session["user_id"]=user["id"]; session["user_name"]=user["name"]; session["role"]=role; session["_csrf"]=secrets.token_urlsafe(32)
    return jsonify({"ok":True,"role":role,"user":json_row(user),"csrf_token":session["_csrf"]})

@app.post("/api/auth/logout")
def api_logout(): session.clear(); return jsonify({"ok":True,"message":"Signed out securely."})

@app.get("/api/auth/me")
def api_me():
    role=session.get("role")
    user=api_user(role) if role else None
    if not user: return api_error("Not authenticated.",401)
    return jsonify({"ok":True,"role":role,"user":json_row(user)})

@app.get("/api/employee/dashboard")
def api_employee_dashboard():
    user=api_user("employee")
    if not user: return api_error("Authentication required.",401)
    eid=user["id"]; today=date.today()
    attendance=query("SELECT * FROM attendance WHERE employee_id=%s AND attendance_date=%s",(eid,today),fetchone=True)
    work=query("SELECT * FROM daily_work WHERE employee_id=%s AND work_date=%s",(eid,today),fetchone=True)
    history=query("SELECT * FROM daily_work WHERE employee_id=%s ORDER BY work_date DESC,id DESC LIMIT 10",(eid,),fetchall=True)
    ah=query("SELECT * FROM attendance WHERE employee_id=%s ORDER BY attendance_date DESC LIMIT 15",(eid,),fetchall=True)
    for r in ah: r["total_hours"]=format_duration(r["check_in"],r["check_out"])
    return jsonify({"ok":True,"employee":json_row(user),"today":today.isoformat(),"attendance":json_row(attendance),"work":json_row(work),"history":[json_row(x) for x in history],"attendance_history":[json_row(x) for x in ah]})

@app.post("/api/employee/check-in")
def api_checkin():
    user=api_user("employee")
    if not user: return api_error("Authentication required.",401)
    data=request.get_json(silent=True) or {}; code=str(data.get("code","")).strip()
    if not re.fullmatch(r"\d{6}",code): return api_error("Enter the six-digit attendance code.")
    today=date.today(); existing=query("SELECT id FROM attendance WHERE employee_id=%s AND attendance_date=%s",(user["id"],today),fetchone=True)
    if existing: return api_error("Your attendance has already been recorded today.",409)
    now=datetime.now(); s=query("SELECT * FROM attendance_sessions WHERE attendance_date=%s AND code=%s AND expires_at >= %s ORDER BY id DESC LIMIT 1",(today,code,now),fetchone=True)
    if not s: return api_error("Invalid or expired attendance code.")
    try: late_after=datetime.strptime(app.config["LATE_AFTER"],"%H:%M").time()
    except ValueError: late_after=time(9,30)
    status="Late" if now.time()>late_after else "Present"
    try: query("INSERT INTO attendance (employee_id,attendance_date,check_in,status,session_id) VALUES (%s,%s,%s,%s,%s)",(user["id"],today,now,status,s["id"]),commit=True)
    except IntegrityError: return api_error("Your attendance has already been recorded today.",409)
    return jsonify({"ok":True,"message":"Attendance marked successfully.","status":status})

@app.post("/api/employee/check-out")
def api_checkout():
    user=api_user("employee")
    if not user: return api_error("Authentication required.",401)
    today=date.today(); a=query("SELECT * FROM attendance WHERE employee_id=%s AND attendance_date=%s",(user["id"],today),fetchone=True)
    if not a: return api_error("Check in before checking out.")
    if a["check_out"]: return api_error("Your workday is already completed.",409)
    w=query("SELECT id FROM daily_work WHERE employee_id=%s AND work_date=%s",(user["id"],today),fetchone=True)
    if not w: return api_error("Please complete today's work entry before checking out.")
    now=datetime.now(); query("UPDATE attendance SET check_out=%s WHERE id=%s",(now,a["id"]),commit=True)
    return jsonify({"ok":True,"message":"Workday completed. Check-out recorded.","check_out":now.isoformat()})

@app.post("/api/employee/work")
def api_work():
    user=api_user("employee")
    if not user: return api_error("Authentication required.",401)
    d=request.get_json(silent=True) or {}; title=str(d.get("work_title","")).strip(); desc=str(d.get("work_description","")).strip(); blockers=str(d.get("blockers","")).strip(); tomorrow=str(d.get("tomorrow_plan","")).strip(); status=str(d.get("status","Not Started"))
    try: progress=max(0,min(100,int(d.get("progress",0))))
    except (ValueError,TypeError): progress=0
    if not title or not desc: return api_error("Work title and description are required.")
    if status not in {"Not Started","In Progress","Completed"}: return api_error("Invalid work status.")
    today=date.today(); existing=query("SELECT id FROM daily_work WHERE employee_id=%s AND work_date=%s",(user["id"],today),fetchone=True)
    if existing:
        query("UPDATE daily_work SET work_title=%s,work_description=%s,progress=%s,status=%s,blockers=%s,tomorrow_plan=%s WHERE id=%s",(title,desc,progress,status,blockers or None,tomorrow or None,existing["id"]),commit=True)
    else:
        query("INSERT INTO daily_work (employee_id,work_date,work_title,work_description,progress,status,blockers,tomorrow_plan) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",(user["id"],today,title,desc,progress,status,blockers or None,tomorrow or None),commit=True)
    return jsonify({"ok":True,"message":"Work entry saved."})

@app.get("/api/admin/dashboard")
def api_admin_dashboard():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    selected=parse_date(request.args.get("date")); emps=query("SELECT e.id,e.employee_code,e.name,e.email,e.designation,e.department,e.phone,e.active,a.attendance_date,a.check_in,a.check_out,a.status AS attendance_status,w.work_title,w.progress,w.status AS work_status,w.blockers,w.tomorrow_plan FROM employees e LEFT JOIN attendance a ON a.employee_id=e.id AND a.attendance_date=%s LEFT JOIN daily_work w ON w.employee_id=e.id AND w.work_date=%s WHERE e.active=1 ORDER BY e.name",(selected,selected),fetchall=True)
    stats={"active":query("SELECT COUNT(*) AS n FROM employees WHERE active=1",fetchone=True)["n"],"checked_in":query("SELECT COUNT(*) AS n FROM attendance WHERE attendance_date=%s",(selected,),fetchone=True)["n"],"checked_out":query("SELECT COUNT(*) AS n FROM attendance WHERE attendance_date=%s AND check_out IS NOT NULL",(selected,),fetchone=True)["n"],"work_records":query("SELECT COUNT(*) AS n FROM daily_work WHERE work_date=%s",(selected,),fetchone=True)["n"]}
    stats["not_checked_in"]=max(0,stats["active"]-stats["checked_in"])
    notes=query("SELECT m.*,a.name AS admin_name FROM meeting_notes m JOIN admins a ON a.id=m.created_by WHERE m.note_date=%s ORDER BY m.created_at DESC",(selected,),fetchall=True)
    return jsonify({"ok":True,"date":selected.isoformat(),"stats":stats,"employees":[json_row(x) for x in emps],"notes":[json_row(x) for x in notes]})

@app.get("/api/admin/employees")
def api_employees():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    search=request.args.get("q","").strip(); dept=request.args.get("department","").strip(); status=request.args.get("status","all")
    clauses=[]; params=[]
    if search: clauses.append("(name LIKE %s OR employee_code LIKE %s OR email LIKE %s)"); term=f"%{search}%"; params += [term,term,term]
    if dept: clauses.append("department=%s"); params.append(dept)
    if status in {"active","inactive"}: clauses.append("active=%s"); params.append(1 if status=="active" else 0)
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    rows=query(f"SELECT id,employee_code,name,email,designation,department,phone,active,created_at FROM employees{where} ORDER BY created_at DESC",tuple(params),fetchall=True)
    deps=query("SELECT DISTINCT department FROM employees ORDER BY department",fetchall=True)
    return jsonify({"ok":True,"employees":[json_row(x) for x in rows],"departments":[x["department"] for x in deps]})

@app.post("/api/admin/employees")
def api_create_employee():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    d=request.get_json(silent=True) or {}; code=str(d.get("employee_code","")).strip(); name=str(d.get("name","")).strip(); email=str(d.get("email","")).strip().lower(); pw=str(d.get("password","")); des=str(d.get("designation","")).strip(); dept=str(d.get("department","")).strip(); phone=str(d.get("phone","")).strip()
    okpw=len(pw)>=10 and bool(re.search(r"[A-Z]",pw)) and bool(re.search(r"[a-z]",pw)) and bool(re.search(r"\d",pw)); okemail=bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email))
    if not all([code,name,email,pw,des,dept]): return api_error("Please complete all required employee fields.")
    if not okemail: return api_error("Invalid employee email address.")
    if not okpw: return api_error("Employee password must be at least 10 characters and include uppercase, lowercase and a number.")
    try: eid=query("INSERT INTO employees (employee_code,name,email,password_hash,designation,department,phone,active) VALUES (%s,%s,%s,%s,%s,%s,%s,1)",(code,name,email,generate_password_hash(pw),des,dept,phone or None),commit=True)
    except IntegrityError: return api_error("Employee code or email already exists.",409)
    return jsonify({"ok":True,"message":"Employee account created.","employee":json_row(query("SELECT * FROM employees WHERE id=%s",(eid,),fetchone=True))}),201

@app.patch("/api/admin/employees/<int:employee_id>/toggle")
def api_toggle_employee(employee_id):
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    row=query("SELECT id FROM employees WHERE id=%s",(employee_id,),fetchone=True)
    if not row: return api_error("Employee not found.",404)
    query("UPDATE employees SET active=IF(active=1,0,1) WHERE id=%s",(employee_id,),commit=True)
    return jsonify({"ok":True,"employee":json_row(query("SELECT id,employee_code,name,email,designation,department,phone,active FROM employees WHERE id=%s",(employee_id,),fetchone=True))})

@app.post("/api/admin/attendance/generate")
def api_generate_code():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    today=date.today(); code=f"{secrets.randbelow(1000000):06d}"; expires=datetime.now()+timedelta(minutes=app.config["CODE_MINUTES"])
    rid=query("INSERT INTO attendance_sessions (attendance_date,code,expires_at) VALUES (%s,%s,%s)",(today,code,expires),commit=True)
    return jsonify({"ok":True,"code":code,"expires_at":expires.strftime("%I:%M %p"),"expires_iso":expires.isoformat(),"id":rid})

@app.get("/api/admin/attendance/current")
def api_current_code():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    row=query("SELECT * FROM attendance_sessions WHERE attendance_date=%s AND expires_at >= %s ORDER BY id DESC LIMIT 1",(date.today(),datetime.now()),fetchone=True)
    if not row: return jsonify({"ok":True,"active":False})
    return jsonify({"ok":True,"active":True,"code":row["code"],"expires_at":row["expires_at"].strftime("%I:%M %p"),"expires_iso":row["expires_at"].isoformat()})

@app.post("/api/admin/notes")
def api_save_note():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    d=request.get_json(silent=True) or {}; nd=parse_date(d.get("note_date")); title=str(d.get("title","")).strip(); discussion=str(d.get("discussion","")).strip(); decisions=str(d.get("decisions","")).strip(); actions=str(d.get("action_items","")).strip()
    if not title or not discussion: return api_error("Topic and discussion are required.")
    rid=query("INSERT INTO meeting_notes (note_date,title,discussion,decisions,action_items,created_by) VALUES (%s,%s,%s,%s,%s,%s)",(nd,title,discussion,decisions or None,actions or None,user["id"]),commit=True)
    return jsonify({"ok":True,"message":"Discussion notes saved.","note":json_row(query("SELECT m.*,a.name AS admin_name FROM meeting_notes m JOIN admins a ON a.id=m.created_by WHERE m.id=%s",(rid,),fetchone=True))}),201

@app.get("/api/admin/notes")
def api_notes():
    user=api_user("admin")
    if not user: return api_error("Authentication required.",401)
    nd=parse_date(request.args.get("date")); rows=query("SELECT m.*,a.name AS admin_name FROM meeting_notes m JOIN admins a ON a.id=m.created_by WHERE m.note_date=%s ORDER BY m.created_at DESC",(nd,),fetchall=True)
    return jsonify({"ok":True,"date":nd.isoformat(),"notes":[json_row(x) for x in rows]})

@app.errorhandler(404)
def api_404(_): return api_error("API endpoint not found.",404)

@app.errorhandler(405)
def api_405(_): return api_error("HTTP method not allowed.",405)

@app.errorhandler(413)
def api_413(_): return api_error("Request body is too large.",413)

@app.errorhandler(500)
def api_500(_): return api_error("Internal server error.",500)


if __name__ == "__main__":
    try:
        ensure_database()
        bootstrap_admin()
    except Exception as exc:
        print("Database initialization failed:", exc)
        raise
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=app.config["DEBUG"])
