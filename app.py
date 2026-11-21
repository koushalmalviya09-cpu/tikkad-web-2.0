import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import date, datetime, timezone
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
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
login_attempts = defaultdict(deque)
booking_attempts = defaultdict(deque)
order_attempts = defaultdict(deque)


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
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            fulfillment_type TEXT NOT NULL CHECK (fulfillment_type IN ('dine_in', 'pickup')),
            table_number TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            total_paise INTEGER NOT NULL CHECK (total_paise > 0),
            payment_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (payment_status IN ('pending', 'paid', 'failed')),
            order_status TEXT NOT NULL DEFAULT 'awaiting_payment'
                CHECK (order_status IN ('awaiting_payment', 'new', 'accepted', 'preparing', 'ready', 'completed', 'cancelled', 'payment_failed')),
            gateway_order_id TEXT UNIQUE,
            payment_id TEXT UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            menu_item_id INTEGER,
            item_name TEXT NOT NULL,
            item_price INTEGER NOT NULL CHECK (item_price >= 0),
            quantity INTEGER NOT NULL CHECK (quantity > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at);
        CREATE INDEX IF NOT EXISTS idx_bookings_date_status ON bookings(booking_date, status);
        CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_gateway_order_id ON orders(gateway_order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
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
        "default-src 'self'; img-src 'self' https://images.unsplash.com https://*.razorpay.com data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' https://checkout.razorpay.com; "
        "connect-src 'self' https://*.razorpay.com; "
        "frame-src https://*.razorpay.com; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self' https://*.razorpay.com"
    )
    if request.path.startswith("/api/staff") or request.path.startswith("/api/orders"):
        response.headers["Cache-Control"] = "no-store"
    return response


def recent_attempts(store, key, limit_seconds=600):
    now = time.time()
    attempts = store[key]
    while attempts and attempts[0] < now - limit_seconds:
        attempts.popleft()
    return attempts


def valid_csrf_token(token_name="csrf_token"):
    csrf_token = request.headers.get("X-CSRF-Token", "")
    expected_token = session.get(token_name, "")
    return bool(expected_token) and secrets.compare_digest(csrf_token, expected_token)


class PaymentGatewayError(Exception):
    pass


def razorpay_is_configured():
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def order_payment_block_reason():
    if not razorpay_is_configured():
        return "Online ordering is not configured yet."
    database_path = DB_PATH.replace("\\", "/")
    if (
        database_path.startswith(("/tmp/", "/var/tmp/"))
        and not RAZORPAY_KEY_ID.startswith("rzp_test_")
    ):
        return "Live payments require persistent order storage. Use Razorpay test keys until storage is upgraded."
    return ""


def razorpay_request(path, method="GET", payload=None):
    credentials = base64.b64encode(
        f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode("utf-8")
    ).decode("ascii")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    gateway_request = urllib.request.Request(
        f"https://api.razorpay.com/v1/{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(gateway_request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        app.logger.warning("Razorpay API request failed: %s", type(error).__name__)
        raise PaymentGatewayError from error


def order_payment_configured():
    return not order_payment_block_reason()


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


@app.route("/api/orders/config")
def order_config():
    if "order_csrf_token" not in session:
        session["order_csrf_token"] = secrets.token_urlsafe(24)
    return jsonify({
        "enabled": order_payment_configured(),
        "keyId": RAZORPAY_KEY_ID if order_payment_configured() else "",
        "csrfToken": session["order_csrf_token"],
        "message": "Online ordering is not available yet. Please contact the restaurant to place an order.",
    })


@app.route("/api/orders", methods=["POST"])
def create_order():
    if not order_payment_configured():
        return jsonify({"error": "Online ordering is not available right now."}), 503
    if not valid_csrf_token("order_csrf_token"):
        return jsonify({"error": "Refresh the page and try again."}), 403

    ip = request.remote_addr or "unknown"
    attempts = recent_attempts(order_attempts, ip)
    if len(attempts) >= 8:
        return jsonify({"error": "Too many order attempts. Please try again later."}), 429
    attempts.append(time.time())

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid order request."}), 400
    customer_name = data.get("name")
    phone = data.get("phone")
    fulfillment_type = data.get("fulfillment")
    table_number = data.get("tableNumber", "")
    notes = data.get("notes", "")
    raw_items = data.get("items")
    if not all(isinstance(value, str) for value in (customer_name, phone, fulfillment_type, table_number, notes)):
        return jsonify({"error": "Enter valid customer and order details."}), 400

    customer_name = customer_name.strip()
    phone = phone.strip()
    table_number = table_number.strip()
    notes = notes.strip()
    if not (2 <= len(customer_name) <= 80):
        return jsonify({"error": "Enter a valid name."}), 400
    digits = "".join(character for character in phone if character.isdigit())
    if not (8 <= len(digits) <= 15):
        return jsonify({"error": "Enter a valid phone number."}), 400
    if fulfillment_type not in {"dine_in", "pickup"}:
        return jsonify({"error": "Choose dine-in or pickup."}), 400
    if len(table_number) > 20 or len(notes) > 300:
        return jsonify({"error": "Order notes or table number are too long."}), 400
    if not isinstance(raw_items, list) or not (1 <= len(raw_items) <= 30):
        return jsonify({"error": "Add at least one menu item to your order."}), 400

    quantities = {}
    for item in raw_items:
        if not isinstance(item, dict):
            return jsonify({"error": "Invalid menu item in order."}), 400
        raw_id = item.get("id")
        quantity = item.get("quantity")
        if isinstance(raw_id, bool) or not str(raw_id).isdigit():
            return jsonify({"error": "Invalid menu item in order."}), 400
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not (1 <= quantity <= 20):
            return jsonify({"error": "Each item quantity must be between 1 and 20."}), 400
        item_id = int(raw_id)
        if item_id <= 0 or quantities.get(item_id, 0) + quantity > 20:
            return jsonify({"error": "Each item quantity must be between 1 and 20."}), 400
        quantities[item_id] = quantities.get(item_id, 0) + quantity

    placeholders = ",".join("?" for _ in quantities)
    with get_db() as db:
        menu_rows = db.execute(f"""
            SELECT id, name, price
            FROM menu_items
            WHERE available = 1 AND id IN ({placeholders})
        """, tuple(quantities)).fetchall()
        if len(menu_rows) != len(quantities):
            return jsonify({"error": "One or more selected items are no longer available."}), 400

        order_lines = [
            {
                "menu_item_id": row["id"],
                "name": row["name"],
                "price": row["price"],
                "quantity": quantities[row["id"]],
            }
            for row in menu_rows
        ]
        total_paise = sum(line["price"] * line["quantity"] * 100 for line in order_lines)
        if total_paise <= 0 or total_paise > 100_000_000:
            return jsonify({"error": "The order total is outside the allowed range."}), 400

        cursor = db.execute("""
            INSERT INTO orders
                (customer_name, phone, fulfillment_type, table_number, notes, total_paise, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            customer_name,
            phone,
            fulfillment_type,
            table_number,
            notes,
            total_paise,
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        ))
        order_id = cursor.lastrowid
        db.executemany("""
            INSERT INTO order_items (order_id, menu_item_id, item_name, item_price, quantity)
            VALUES (?, ?, ?, ?, ?)
        """, [
            (order_id, line["menu_item_id"], line["name"], line["price"], line["quantity"])
            for line in order_lines
        ])

    try:
        gateway_order = razorpay_request("orders", method="POST", payload={
            "amount": total_paise,
            "currency": "INR",
            "receipt": f"kth-{order_id}",
            "notes": {"fulfillment": fulfillment_type},
        })
        if not isinstance(gateway_order, dict):
            raise PaymentGatewayError("Invalid Razorpay order response")
        gateway_order_id = gateway_order.get("id")
        if (
            not isinstance(gateway_order_id, str)
            or re.fullmatch(r"order_[A-Za-z0-9]+", gateway_order_id) is None
            or gateway_order.get("amount") != total_paise
            or gateway_order.get("currency") != "INR"
        ):
            raise PaymentGatewayError("Invalid Razorpay order response")
        with get_db() as db:
            db.execute("UPDATE orders SET gateway_order_id = ? WHERE id = ?", (gateway_order_id, order_id))
    except PaymentGatewayError:
        with get_db() as db:
            db.execute("""
                UPDATE orders SET payment_status = 'failed', order_status = 'payment_failed'
                WHERE id = ?
            """, (order_id,))
        return jsonify({"error": "Payment setup failed. Please try again in a moment."}), 502

    return jsonify({
        "orderId": order_id,
        "razorpayOrderId": gateway_order_id,
        "amount": total_paise,
        "currency": "INR",
        "keyId": RAZORPAY_KEY_ID,
        "name": "Khandwa Tikkad Hotel",
        "customerName": customer_name,
        "phone": phone,
    }), 201


@app.route("/api/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order_payment(order_id):
    if not order_payment_configured():
        return jsonify({"error": "Online payment verification is not available right now."}), 503
    if not valid_csrf_token("order_csrf_token"):
        return jsonify({"error": "Refresh the page and try again."}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payment confirmation."}), 400
    razorpay_order_id = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature = data.get("razorpay_signature")
    if not all(isinstance(value, str) and value for value in (razorpay_order_id, payment_id, signature)):
        return jsonify({"error": "Payment confirmation is incomplete."}), 400
    if (
        re.fullmatch(r"order_[A-Za-z0-9]+", razorpay_order_id) is None
        or re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id) is None
        or re.fullmatch(r"[a-fA-F0-9]{64}", signature) is None
    ):
        return jsonify({"error": "Payment confirmation is invalid."}), 400

    with get_db() as db:
        order = db.execute("""
            SELECT id, total_paise, payment_status, gateway_order_id, payment_id
            FROM orders WHERE id = ?
        """, (order_id,)).fetchone()
    if not order or order["gateway_order_id"] != razorpay_order_id:
        return jsonify({"error": "Order could not be verified."}), 404

    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{razorpay_order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return jsonify({"error": "Payment signature is invalid."}), 400
    if order["payment_status"] == "paid":
        if order["payment_id"] == payment_id:
            return jsonify({"success": True, "orderId": order_id})
        return jsonify({"error": "This order has already been paid."}), 409

    try:
        payment = razorpay_request(f"payments/{payment_id}")
    except PaymentGatewayError:
        return jsonify({"error": "Payment verification is temporarily unavailable. Please contact the restaurant before retrying."}), 502
    if (
        not isinstance(payment, dict)
        or payment.get("order_id") != razorpay_order_id
        or payment.get("amount") != order["total_paise"]
        or payment.get("currency") != "INR"
        or payment.get("status") != "captured"
        or payment.get("captured") is not True
    ):
        return jsonify({"error": "Payment has not been captured. Please check with your bank or try again."}), 402

    with get_db() as db:
        cursor = db.execute("""
            UPDATE orders
            SET payment_status = 'paid', order_status = 'new', payment_id = ?
            WHERE id = ? AND payment_status = 'pending'
        """, (payment_id, order_id))
        if cursor.rowcount == 0:
            current = db.execute("SELECT payment_status, payment_id FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not current or current["payment_status"] != "paid" or current["payment_id"] != payment_id:
                return jsonify({"error": "Order payment status changed. Refresh and check your order."}), 409
    return jsonify({"success": True, "orderId": order_id}), 200


@app.route("/api/payments/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    if not RAZORPAY_WEBHOOK_SECRET:
        return jsonify({"error": "Payment webhook is not configured."}), 503

    raw_body = request.get_data(cache=True)
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected_signature, signature):
        return jsonify({"error": "Invalid webhook signature."}), 400

    event = request.get_json(silent=True)
    if not isinstance(event, dict):
        return jsonify({"error": "Invalid webhook payload."}), 400
    if event.get("event") != "payment.captured":
        return jsonify({"success": True})

    payload = event.get("payload", {})
    payment_payload = payload.get("payment", {}) if isinstance(payload, dict) else {}
    payment_entity = payment_payload.get("entity", {}) if isinstance(payment_payload, dict) else {}
    if not isinstance(payment_entity, dict):
        return jsonify({"error": "Invalid payment event."}), 400
    gateway_order_id = payment_entity.get("order_id")
    payment_id = payment_entity.get("id")
    amount = payment_entity.get("amount")
    if (
        not isinstance(gateway_order_id, str)
        or re.fullmatch(r"order_[A-Za-z0-9]+", gateway_order_id) is None
        or not isinstance(payment_id, str)
        or re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id) is None
        or isinstance(amount, bool)
        or not isinstance(amount, int)
        or payment_entity.get("currency") != "INR"
        or payment_entity.get("captured") is not True
    ):
        return jsonify({"error": "Invalid captured payment details."}), 400

    with get_db() as db:
        cursor = db.execute("""
            UPDATE orders
            SET payment_status = 'paid', order_status = 'new', payment_id = ?
            WHERE gateway_order_id = ? AND total_paise = ? AND payment_status != 'paid'
        """, (payment_id, gateway_order_id, amount))
        if cursor.rowcount == 0:
            order = db.execute("""
                SELECT payment_status, payment_id
                FROM orders WHERE gateway_order_id = ? AND total_paise = ?
            """, (gateway_order_id, amount)).fetchone()
            if not order:
                app.logger.warning("Razorpay captured payment did not match a local order")
                return jsonify({"error": "Matching order not found."}), 500
            if order["payment_status"] != "paid" or order["payment_id"] != payment_id:
                return jsonify({"error": "Payment conflicts with the saved order."}), 409
    return jsonify({"success": True})


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


@app.route("/api/staff/orders")
@staff_required
def staff_orders():
    with get_db() as db:
        rows = db.execute("""
            SELECT
                o.id, o.customer_name, o.phone, o.fulfillment_type, o.table_number,
                o.notes, o.total_paise, o.payment_status, o.order_status,
                o.created_at, oi.item_name, oi.item_price, oi.quantity
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.id
            WHERE o.id IN (
                SELECT id FROM orders ORDER BY created_at DESC LIMIT 500
            )
            ORDER BY o.created_at DESC, oi.id
        """).fetchall()

    orders_by_id = {}
    for row in rows:
        order = orders_by_id.get(row["id"])
        if order is None:
            order = {
                "id": row["id"],
                "customer_name": row["customer_name"],
                "phone": row["phone"],
                "fulfillment_type": row["fulfillment_type"],
                "table_number": row["table_number"],
                "notes": row["notes"],
                "total_paise": row["total_paise"],
                "payment_status": row["payment_status"],
                "order_status": row["order_status"],
                "created_at": row["created_at"],
                "items": [],
            }
            orders_by_id[row["id"]] = order
        if row["item_name"] is not None:
            order["items"].append({
                "item_name": row["item_name"],
                "item_price": row["item_price"],
                "quantity": row["quantity"],
            })
    return jsonify({"orders": list(orders_by_id.values())})


@app.route("/api/staff/orders/<int:order_id>", methods=["PATCH"])
@staff_required
def update_order(order_id):
    if not valid_csrf_token():
        return jsonify({"error": "Invalid security token"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid order update."}), 400
    status = data.get("status")
    if not isinstance(status, str) or status not in {
        "new", "accepted", "preparing", "ready", "completed", "cancelled"
    }:
        return jsonify({"error": "Invalid order status."}), 400

    with get_db() as db:
        cursor = db.execute("""
            UPDATE orders SET order_status = ?
            WHERE id = ? AND payment_status = 'paid'
        """, (status, order_id))
        if cursor.rowcount == 0:
            order = db.execute("SELECT id, payment_status FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Order not found."}), 404
            return jsonify({"error": "Only paid orders can be processed."}), 409
    return jsonify({"success": True})


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
