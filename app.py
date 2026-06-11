import os
import json
import time
import signal
import subprocess
import shutil
import zipfile
import hashlib
import psutil
import threading
from pathlib import Path
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, abort

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super-vivid-fast-node-python-v3")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
SERVERS_DIR = BASE_DIR / "servers"
SERVERS_DIR.mkdir(exist_ok=True)

RUNNING_PROCESSES = {}
RESET_TIMERS = {}

# ─── DATA LOADER & SAVER ──────────────────────────────────────────────────────
def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {
        "servers": {},
        "users": {},
        "settings": {
            "site_name": "—͞SᎻꫝᎮᎮƝ᥆ꤪꤨꤨ  𝐂𝚘𝙳𝚎𝚡",
            "maintenance": False,
            "maintenance_msg": "System upgrading.",
            "theme_color": "#00ff41",
            "admin_password_hash": hashlib.sha256("SHAPPNO004X".encode()).hexdigest(),
            "global_user_password_hash": hashlib.sha256("123456".encode()).hexdigest()
        }
    }

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, default=str))

def get_theme_color():
    return load_data().get("settings", {}).get("theme_color", "#00ff41")

def get_site_name():
    return load_data().get("settings", {}).get("site_name", "—͞SᎻꫝᎮᎮƝ᥆ꤪꤨꤨ  𝐂𝚘𝙳𝚎𝚡")

@app.context_processor
def inject_global_template_vars():
    return {
        "theme_color": get_theme_color(),
        "site_name": get_site_name()
    }

# ─── ROUTE DECORATORS ─────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ─── ENGINE CORE SCRIPT RUNNER / CRASH RECOVERY LOGIC ────────────────────────
def is_process_alive(pid):
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def kill_process(pid):
    try:
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            try: child.terminate()
            except: pass
        p.terminate()
        p.wait(timeout=3)
    except:
        pass

def spawn_project_process(name, cfg):
    extract_dir = SERVERS_DIR / name / "extracted"
    log_path = SERVERS_DIR / name / "logs.txt"
    
    # Custom main path runner (As requested)
    custom_cmd = cfg.get("exec_command", "").strip()
    if custom_cmd:
        cmd = custom_cmd.split()
    else:
        # Default fallback
        main_file = "main.py"
        if (extract_dir / "app.js").exists(): main_file = "app.js"
        if (extract_dir / "index.js").exists(): main_file = "index.js"
        
        if cfg.get("runtime") == "node" or main_file.endswith(".js"):
            cmd = ["node", main_file]
        else:
            cmd = ["python", "-u", main_file]
            
    try:
        log_file = open(log_path, "a")
        log_file.write(f"\n--- SYSTEM INSTANT START AT {datetime.now()} ---\n")
        env = os.environ.copy()
        env["PORT"] = str(cfg.get("port", 8080))
        
        proc = subprocess.Popen(cmd, cwd=str(extract_dir), stdout=log_file, stderr=log_file, env=env, preexec_fn=os.setsid if hasattr(os, "setsid") else None)
        RUNNING_PROCESSES[name] = {"proc": proc, "log_file": log_file}
        return proc.pid
    except Exception as e:
        try:
            with open(log_path, "a") as f:
                f.write(f"\nExecution Fail Error: {str(e)}\n")
        except: pass
        return None

# ─── {CRITICAL VERY IMPORTANT} BACKGROUND RESURRECTION THREAD ────────────────
# Render/HF/Railway তে ক্র্যাশ করলে বা অফ হয়ে গেলে সাথে সাথে অটোমেটিক অন করার লুপ
def auto_healing_supervisor_loop():
    while True:
        try:
            data = load_data()
            changed = False
            for name, cfg in list(data.get("servers", {}).items()):
                if cfg.get("status") == "running":
                    pid = cfg.get("pid")
                    if not pid or not is_process_alive(pid):
                        # Script turned off unexpectedly! Revive instantly!
                        new_pid = spawn_project_process(name, cfg)
                        if new_pid:
                            data["servers"][name]["pid"] = new_pid
                            changed = True
            if changed:
                save_data(data)
        except:
            pass
        time.sleep(3) # ৩ সেকেন্ড পরপর ব্যাকগ্রাউন্ড স্ক্যানিং হবে

threading.Thread(target=auto_healing_supervisor_loop, daemon=True).start()

# ─── AUTOMATIC RESTART RUNTIME TRACKER ────────────────────────────────────────
def _auto_reset_seconds(cfg):
    ar = cfg.get("auto_reset", {})
    y, d, h, m, s = ar.get("years", 0), ar.get("days", 0), ar.get("hours", 0), ar.get("minutes", 0), ar.get("seconds", 0)
    return int(y * 31536000 + d * 86400 + h * 3600 + m * 60 + s)

def _execute_scheduled_reset(name):
    try:
        data = load_data()
        cfg = data["servers"].get(name)
        if not cfg: return
        
        pid = cfg.get("pid")
        if pid: kill_process(pid)
        
        if name in RUNNING_PROCESSES:
            try: RUNNING_PROCESSES[name]["log_file"].close()
            except: pass
            del RUNNING_PROCESSES[name]
            
        new_pid = spawn_project_process(name, cfg)
        if new_pid:
            data["servers"][name]["pid"] = new_pid
            data["servers"][name]["status"] = "running"
            save_data(data)
            
        # Re-schedule next loop interval continuously
        total = _auto_reset_seconds(cfg)
        if cfg.get("auto_reset", {}).get("enabled") and total > 0:
            _schedule_reset_timer(name, total)
    except:
        pass

def _schedule_reset_timer(name, total_seconds):
    if name in RESET_TIMERS:
        try: RESET_TIMERS[name]["timer"].cancel()
        except: pass
    t = threading.Timer(total_seconds, _execute_scheduled_reset, args=[name])
    t.daemon = True
    t.start()
    RESET_TIMERS[name] = {"timer": t}

# ─── AUTHENTICATION ROUTES ────────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        data = load_data()
        
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        master_user_hash = data["settings"].get("global_user_password_hash")
        
        if input_hash == master_user_hash:
            session["username"] = username
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid System Dynamic Password")
    return render_template("login.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        data = load_data()
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        
        if input_hash == data["settings"].get("admin_password_hash"):
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        else:
            return render_template("admin_login.html", error="Access Denied. Fraudulent Activity Logged.")
    return render_template("admin_login.html")

# ─── DASHBOARD CORE ───────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    username = session["username"]
    data = load_data()
    user_servers = {k: v for k, v in data["servers"].items() if v.get("owner") == username}
    running_count = sum(1 for v in user_servers.values() if v.get("status") == "running")
    return render_template("dashboard.html", servers=user_servers, running=running_count, total=len(user_servers), username=username)

@app.route("/api/stats")
def system_stats():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent
    })

# ─── PROJECT / SERVER ACTIONS ─────────────────────────────────────────────────
@app.route("/server/create", methods=["POST"])
@login_required
def create_server():
    name = request.form.get("name", "").strip().replace(" ", "-").lower()
    runtime = request.form.get("runtime", "python")
    if not name: return redirect(url_for("dashboard"))
    
    data = load_data()
    if name in data["servers"]: return redirect(url_for("dashboard"))
    
    data["servers"][name] = {
        "name": name, "owner": session["username"], "runtime": runtime, "status": "stopped",
        "exec_command": "", "port": 8080, "pid": None, "created": datetime.now().isoformat(),
        "auto_reset": {"enabled": False, "years": 0, "days": 0, "hours": 0, "minutes": 0, "seconds": 0}
    }
    save_data(data)
    (SERVERS_DIR / name / "extracted").mkdir(parents=True, exist_ok=True)
    return redirect(url_for("server_detail", name=name))

@app.route("/server/<name>/save_exec", methods=["POST"])
@login_required
def save_exec_command(name):
    data = load_data()
    if name in data["servers"]:
        cmd = request.get_json().get("exec_command", "").strip()
        data["servers"][name]["exec_command"] = cmd
        save_data(data)
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route("/server/<name>")
@login_required
def server_detail(name):
    data = load_data()
    cfg = data["servers"].get(name)
    if not cfg: return "Project Not Found", 404
    
    extract_dir = SERVERS_DIR / name / "extracted"
    files = []
    if extract_dir.exists():
        for f in extract_dir.iterdir():
            files.append({"path": f.name, "type": "file" if f.is_file() else "dir", "size": f.stat().st_size if f.is_file() else 0})
            
    return render_template("server.html", server_name=name, config=cfg, files=files)

@app.route("/server/<name>/start", methods=["POST"])
@login_required
def start_server(name):
    data = load_data()
    cfg = data["servers"].get(name)
    if cfg:
        if cfg.get("pid"): kill_process(cfg.get("pid"))
        pid = spawn_project_process(name, cfg)
        if pid:
            data["servers"][name]["pid"] = pid
            data["servers"][name]["status"] = "running"
            save_data(data)
            total = _auto_reset_seconds(cfg)
            if cfg.get("auto_reset", {}).get("enabled") and total > 0:
                _schedule_reset_timer(name, total)
            return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/server/<name>/stop", methods=["POST"])
@login_required
def stop_server(name):
    data = load_data()
    cfg = data["servers"].get(name)
    if cfg:
        pid = cfg.get("pid")
        if pid: kill_process(pid)
        data["servers"][name]["pid"] = None
        data["servers"][name]["status"] = "stopped"
        save_data(data)
        if name in RUNNING_PROCESSES: del RUNNING_PROCESSES[name]
        if name in RESET_TIMERS:
            try: RESET_TIMERS[name]["timer"].cancel()
            except: pass
            del RESET_TIMERS[name]
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/server/<name>/upload", methods=["POST"])
@login_required
def upload_file(name):
    if "file" not in request.files: return jsonify({"success": False})
    f = request.files["file"]
    extract_dir = SERVERS_DIR / name / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = extract_dir / f.filename
    f.save(str(target_path))
    
    if f.filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(str(target_path), "r") as z:
                z.extractall(str(extract_dir))
            target_path.unlink()
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
            
    return jsonify({"success": True})

@app.route("/server/<name>/logs")
@login_required
def get_logs(name):
    log_path = SERVERS_DIR / name / "logs.txt"
    if log_path.exists():
        return jsonify({"logs": log_path.read_text()[-15000:]}) # Last 15k chars format view
    return jsonify({"logs": "Terminal clean & silent."})

@app.route("/server/<name>/logs/clear", methods=["POST"])
@login_required
def clear_logs(name):
    log_path = SERVERS_DIR / name / "logs.txt"
    if log_path.exists(): log_path.write_text("--- CONSOLE WIPED BY USER ---\n")
    return jsonify({"success": True})

@app.route("/server/<name>/auto-reset/settings", methods=["POST"])
@login_required
def save_reset_settings(name):
    payload = request.get_json()
    data = load_data()
    if name in data["servers"]:
        data["servers"][name]["auto_reset"] = payload
        save_data(data)
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/server/delete/<name>", methods=["POST"])
@login_required
def delete_server(name):
    data = load_data()
    if name in data["servers"]:
        pid = data["servers"][name].get("pid")
        if pid: kill_process(pid)
        del data["servers"][name]
        save_data(data)
        shutil.rmtree(SERVERS_DIR / name, ignore_errors=True)
    return redirect(url_for("dashboard"))

# ─── MASTER ADMIN PANEL MANAGEMENT ROUTES ─────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_panel():
    data = load_data()
    users_list = []
    for username, udata in data["users"].items():
        user_srv = [v for v in data["servers"].values() if v.get("owner") == username]
        users_list.append({
            "username": username,
            "projects": len(user_srv),
            "running": sum(1 for s in user_srv if s.get("status") == "running")
        })
    
    running_count = sum(1 for v in data["servers"].values() if v.get("status") == "running")
    return render_template("admin_panel.html", users=users_list, total_users=len(users_list), total_projects=len(data["servers"]), running=running_count, total_files=99, settings=data["settings"])

@app.route("/admin/save_master_settings", methods=["POST"])
@admin_required
def save_master_settings():
    site_name = request.form.get("site_name", "").strip()
    u_pass = request.form.get("user_password", "").strip()
    a_pass = request.form.get("admin_password", "").strip()
    
    data = load_data()
    if site_name: data["settings"]["site_name"] = site_name
    if u_pass: data["settings"]["global_user_password_hash"] = hashlib.sha256(u_pass.encode()).hexdigest()
    if a_pass: data["settings"]["admin_password_hash"] = hashlib.sha256(a_pass.encode()).hexdigest()
    
    save_data(data)
    return redirect(url_for("admin_panel"))

# ─── {VERY VERY IMPORTANT} ALL PAKES ONE-TAP BACKGROUND DEPLOYER ──────────────
@app.route("/admin/install_all_pakes_global", methods=["POST"])
@admin_required
def install_all_pakes_global():
    # গ্লোবাল মাস্টার ইনস্টলার প্যাকেজ ডিপ্লয়মেন্ট রানিং
    pakes = ["flask", "fastapi", "requests", "python-telegram-bot", "aiohttp", "discord.py", "pymongo", "redis", "psutil", "uvicorn"]
    def bg_install():
        for p in pakes:
            subprocess.run(["pip", "install", "--upgrade", p])
    threading.Thread(target=bg_install, daemon=True).start()
    return jsonify({"success": True})

@app.route("/admin/user/<username>/delete", methods=["POST"])
@admin_required
def delete_user(username):
    data = load_data()
    if username in data["users"]:
        del data["users"][username]
        # Clear their bots
        to_del = [k for k, v in data["servers"].items() if v.get("owner") == username]
        for k in to_del:
            pid = data["servers"][k].get("pid")
            if pid:
                kill_process(pid)
            del data["servers"][k]
            shutil.rmtree(SERVERS_DIR / k, ignore_errors=True)
        save_data(data)
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    # পরিবেশের পোর্ট চেক করবে, না থাকলে ডিফল্ট ১০০০০ পোর্ট নেবে
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)