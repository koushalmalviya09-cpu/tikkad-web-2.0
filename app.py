import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import date, datetime
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "hotel.db"))
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
LEGACY_DB_PATH = os.path.join(BASE_DIR, "hotel.db")
if (
    os.environ.get("RENDER")
    and os.path.abspath(DB_PATH) != os.path.abspath(LEGACY_DB_PATH)
    and not os.path.exists(DB_PATH)
    and os.path.isfile(LEGACY_DB_PATH)
):
    source = sqlite3.connect(LEGACY_DB_PATH)
    destination = sqlite3.connect(DB_PATH)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true",
    PERMANENT_SESSION_LIFETIME=43200,
    MAX_CONTENT_LENGTH=16 * 1024,
)
if os.environ.get("RENDER"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

STAFF_CODE = os.environ.get("STAFF_ACCESS_CODE")
if STAFF_CODE and len(STAFF_CODE) < 8:
    raise RuntimeError("STAFF_ACCESS_CODE must contain at least 8 characters.")
STAFF_CODE_HASH = generate_password_hash(STAFF_CODE) if STAFF_CODE else None
login_attempts = defaultdict(deque)
booking_attempts = defaultdict(deque)


@contextmanager
def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            guests INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            ip_address TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price INTEGER NOT NULL CHECK (price >= 0),
            image_url TEXT NOT NULL DEFAULT '',
            display_order INTEGER NOT NULL DEFAULT 0,
            available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1))
        );
        CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at);
        CREATE INDEX IF NOT EXISTS idx_bookings_date_status ON bookings(booking_date, status);
        """)
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
            db.executemany("""
                INSERT INTO menu_items
                    (name, category, description, price, image_url, display_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("Butter Chicken", "Chef's special", "Slow-cooked chicken in a rich, creamy tomato masala.", 320,
                 "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=900&q=85", 1),
                ("Paneer Tikka", "Tandoor", "Smoky paneer marinated with house spices and grilled to order.", 220,
                 "https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?auto=format&fit=crop&w=900&q=85", 2),
                ("Masala Tikkad", "Fresh from the tawa", "Warm, freshly made tikkad with a savoury masala finish.", 60,
                 "https://images.unsplash.com/photo-1574653853027-5382a3d23a15?auto=format&fit=crop&w=900&q=85", 3),
            ])


init_db()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https://images.unsplash.com data:; "
        "style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.path.startswith("/api/staff"):
        response.headers["Cache-Control"] = "no-store"
    return response


def recent_attempts(store, key, limit_seconds=600):
    now = time.time()
    attempts = store[key]
    while attempts and attempts[0] < now - limit_seconds:
        attempts.popleft()
    return attempts


def valid_csrf_token():
    csrf_token = request.headers.get("X-CSRF-Token", "")
    return secrets.compare_digest(csrf_token, session.get("csrf_token", ""))


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_authenticated"):
            return jsonify({"error": "Staff login required"}), 401
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(24)
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/menu")
def menu_page():
    return send_from_directory(BASE_DIR, "menu.html")


@app.route("/<path:filename>")
def static_files(filename):
    allowed_files = {
        "index.html", "menu.html", "staff.html",
        "styles.css", "menu.css", "staff.css",
        "script.js", "menu.js", "staff.js",
    }
    if filename not in allowed_files:
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(BASE_DIR, filename)


@app.route("/api/menu")
def public_menu():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, name, category, description, price, image_url
            FROM menu_items
            WHERE available = 1
            ORDER BY display_order, name
        """).fetchall()
    return jsonify({"items": [dict(row) for row in rows]})


@app.route("/api/bookings", methods=["POST"])
def create_booking():
    ip = request.remote_addr or "unknown"
    attempts = recent_attempts(booking_attempts, ip)
    if len(attempts) >= 12:
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    attempts.append(time.time())

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid booking request."}), 400
    name = data.get("name")
    phone = data.get("phone")
    booking_date = data.get("date")
    booking_time = data.get("time")
    if not all(isinstance(value, str) for value in (name, phone, booking_date, booking_time)):
        return jsonify({"error": "Enter valid booking details."}), 400
    name = name.strip()
    phone = phone.strip()
    booking_date = booking_date.strip()
    booking_time = booking_time.strip()

    try:
        raw_guests = data.get("guests", 0)
        if isinstance(raw_guests, bool) or not str(raw_guests).isdigit():
            raise ValueError
        guests = int(raw_guests)
    except (TypeError, ValueError):
        guests = 0

    if not (2 <= len(name) <= 80):
        return jsonify({"error": "Enter a valid name."}), 400
    digits = "".join(character for character in phone if character.isdigit())
    if not (8 <= len(digits) <= 15):
        return jsonify({"error": "Enter a valid phone number."}), 400
    try:
        selected_date = date.fromisoformat(booking_date)
    except ValueError:
        return jsonify({"error": "Enter a valid booking date."}), 400
    if selected_date.isoformat() != booking_date:
        return jsonify({"error": "Enter a valid booking date."}), 400
    if selected_date < date.today():
        return jsonify({"error": "The booking date cannot be in the past."}), 400
    if booking_time not in {"12:00", "13:00", "14:00", "18:00", "19:00", "20:00", "21:00"}:
        return jsonify({"error": "Select a valid booking time."}), 400
    if not (1 <= guests <= 20):
        return jsonify({"error": "Enter a valid guest count."}), 400

    with get_db() as db:
        cursor = db.execute("""
            INSERT INTO bookings
                (name, phone, booking_date, booking_time, guests, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'new', ?)
        """, (name, phone, booking_date, booking_time, guests, datetime.utcnow().isoformat(timespec="seconds") + "Z"))
        booking_id = cursor.lastrowid

    return jsonify({"success": True, "id": booking_id}), 201


@app.route("/api/staff/login", methods=["POST"])
def staff_login():
    if STAFF_CODE_HASH is None:
        return jsonify({"error": "Staff access is not configured on this server."}), 503

    ip = request.remote_addr or "unknown"
    attempts = recent_attempts(login_attempts, ip)
    if len(attempts) >= 5:
        return jsonify({"error": "Too many login attempts. Try again in 10 minutes."}), 429

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid login request."}), 400
    code = str(data.get("code", ""))
    if not check_password_hash(STAFF_CODE_HASH, code):
        attempts.append(time.time())
        return jsonify({"error": "Incorrect staff access code."}), 401

    login_attempts[ip].clear()
    session.clear()
    session.permanent = True
    session["staff_authenticated"] = True
    session["csrf_token"] = secrets.token_urlsafe(24)
    return jsonify({"success": True, "csrfToken": session["csrf_token"]})


@app.route("/api/staff/logout", methods=["POST"])
@staff_required
def staff_logout():
    if not valid_csrf_token():
        return jsonify({"error": "Invalid security token"}), 403
    session.clear()
    return jsonify({"success": True})


@app.route("/api/staff/session")
@staff_required
def staff_session():
    return jsonify({"success": True, "csrfToken": session["csrf_token"]})


@app.route("/api/staff/bookings")
@staff_required
def staff_bookings():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, name, phone, booking_date, booking_time, guests, status, created_at
            FROM bookings
            ORDER BY created_at DESC
            LIMIT 500
        """).fetchall()
    return jsonify({"bookings": [dict(row) for row in rows]})


@app.route("/api/staff/bookings/<int:booking_id>", methods=["PATCH"])
@staff_required
def update_booking(booking_id):
    if not valid_csrf_token():
        return jsonify({"error": "Invalid security token"}), 403

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid booking update."}), 400
    status = str(data.get("status", ""))
    if status not in {"new", "confirmed", "cancelled"}:
        return jsonify({"error": "Invalid booking status"}), 400

    with get_db() as db:
        cursor = db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Booking not found"}), 404
    return jsonify({"success": True})


@app.route("/api/staff/bookings/<int:booking_id>", methods=["DELETE"])
@staff_required
def delete_booking(booking_id):
    if not valid_csrf_token():
        return jsonify({"error": "Invalid security token"}), 403

    with get_db() as db:
        cursor = db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Booking not found"}), 404
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500, debug=False)
