import json
import os
import secrets
import time
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

app = Flask(__name__)
CONFIG_FILE = "config.json"
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=16 * 1024,
)

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH")
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_ATTEMPTS = 5
login_attempts = {}


def is_authenticated():
    return session.get("authenticated") is True


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if is_authenticated():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Login required."}), 401
        return redirect(url_for("login", next=request.path))

    return wrapped_view


def get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_protected():
    supplied_token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    return secrets.compare_digest(supplied_token or "", session.get("csrf_token", ""))


@app.context_processor
def inject_security_context():
    return {"csrf_token": get_csrf_token(), "authenticated": is_authenticated()}


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
        "connect-src 'self'; frame-ancestors 'none'"
    )
    if is_authenticated():
        response.headers["Cache-Control"] = "no-store"
    return response


def login_is_rate_limited(client_id):
    now = time.monotonic()
    attempts = [attempt for attempt in login_attempts.get(client_id, []) if now - attempt < LOGIN_WINDOW_SECONDS]
    login_attempts[client_id] = attempts
    return len(attempts) >= MAX_LOGIN_ATTEMPTS


def record_login_attempt(client_id):
    login_attempts.setdefault(client_id, []).append(time.monotonic())


def load_config():
    """Loads saved settings from config.json if it exists."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "webhook_url": "",
        "username": "smasher",
        "avatar_url": "https://i.imgur.com/4M34hi2.png",
    }


def save_config(config):
    """Saves updated settings to config.json."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)


@app.route("/")
@login_required
def index():
    """Renders the message sender page."""
    return render_template("index.html")


@app.route("/settings")
@login_required
def settings():
    """Renders the configuration page."""
    config = load_config()
    return render_template("settings.html", config=config)


@app.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("index"))

    next_url = request.args.get("next", "/") if request.method == "GET" else request.form.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    if request.method == "POST":
        if not csrf_protected():
            return render_template("login.html", error="Invalid request.", next_url=next_url), 400

        client_id = request.remote_addr or "unknown"
        if login_is_rate_limited(client_id):
            return render_template("login.html", error="Too many attempts. Try again later.", next_url=next_url), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid_login = (
            bool(APP_PASSWORD_HASH)
            and secrets.compare_digest(username, APP_USERNAME)
            and check_password_hash(APP_PASSWORD_HASH, password)
        )
        if valid_login:
            session.clear()
            session["authenticated"] = True
            get_csrf_token()
            return redirect(next_url)

        record_login_attempt(client_id)
        return render_template("login.html", error="Invalid username or password.", next_url=next_url), 401

    return render_template("login.html", error=None, next_url=next_url)


@app.post("/logout")
@login_required
def logout():
    if not csrf_protected():
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/config", methods=["POST"])
@login_required
def update_config():
    """Saves updated configuration from web interface."""
    if not csrf_protected():
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    data = request.get_json(silent=True) or {}
    webhook_url = data.get("webhook_url", "").strip()
    username = data.get("username", "").strip() or "smasher"
    avatar_url = (
        data.get("avatar_url", "").strip() or "https://i.imgur.com/4M34hi2.png"
    )

    parsed_webhook = urlparse(webhook_url)
    if (
        parsed_webhook.scheme != "https"
        or parsed_webhook.netloc != "discord.com"
        or not parsed_webhook.path.startswith("/api/webhooks/")
    ):
        return jsonify({"status": "error", "message": "Invalid Discord Webhook URL"}), 400

    config = {
        "webhook_url": webhook_url,
        "username": username,
        "avatar_url": avatar_url,
    }
    save_config(config)
    return jsonify({"status": "success", "message": "Settings saved successfully!"})


@app.route("/api/send", methods=["POST"])
@login_required
def send_webhook():
    """Handles posting messages to the Discord Webhook."""
    if not csrf_protected():
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    data = request.get_json(silent=True) or {}
    config = load_config()

    webhook_url = config.get("webhook_url")
    parsed_webhook = urlparse(webhook_url or "")
    if (
        parsed_webhook.scheme != "https"
        or parsed_webhook.netloc != "discord.com"
        or not parsed_webhook.path.startswith("/api/webhooks/")
    ):
        return jsonify({"status": "error", "message": "Webhook URL is not configured!"}), 400

    content = str(data.get("content", "")).strip()[:2000]
    image_url = str(data.get("image_url", "")).strip()[:2000]

    if not content and not image_url:
        return jsonify({"status": "error", "message": "Cannot send empty message!"}), 400

    payload = {
        "username": config["username"],
        "avatar_url": config["avatar_url"],
        "content": content,
    }

    if image_url:
        payload["embeds"] = [{"image": {"url": image_url}}]

    try:
        json_data = json.dumps(payload).encode("utf-8")
        req = Request(
            webhook_url,
            data=json_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            if response.status in (200, 204):
                return jsonify({"status": "success", "message": "Message sent successfully!"})
            else:
                body = response.read().decode("utf-8", errors="ignore")
                return jsonify({"status": "error", "message": f"Discord API {response.status}: {body}"}), 400

    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        return jsonify({"status": "error", "message": f"HTTP {e.code}: {error_body}"}), 400
    except URLError as e:
        return jsonify({"status": "error", "message": f"Connection Error: {e.reason}"}), 500
    except Exception:
        return jsonify({"status": "error", "message": "Unexpected server error."}), 500


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)