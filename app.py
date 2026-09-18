import json
import os
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_CONFIG = {
    "webhook_url": "",
    "username": "smasher",
    "avatar_url": "https://i.imgur.com/4M34hi2.png",
}
app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024,
)


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
    return response


def load_config():
    """Loads saved settings from config.json if it exists."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
            saved_config = json.load(config_file)
        if isinstance(saved_config, dict):
            return {**DEFAULT_CONFIG, **saved_config}
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    """Saves updated settings to config.json."""
    directory = os.path.dirname(CONFIG_FILE)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False
    ) as temporary_file:
        json.dump(config, temporary_file, indent=4)
        temporary_file.write("\n")
        temporary_path = temporary_file.name
    os.replace(temporary_path, CONFIG_FILE)


def clean_text(value, maximum_length):
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum_length]


def is_valid_webhook_url(value):
    parsed_url = urlparse(value)
    return (
        parsed_url.scheme == "https"
        and parsed_url.netloc == "discord.com"
        and parsed_url.path.startswith("/api/webhooks/")
        and len(parsed_url.path.split("/")) >= 5
    )


@app.route("/")
def index():
    """Renders the message sender page."""
    return render_template("index.html")


@app.route("/settings")
def settings():
    """Renders the configuration page."""
    config = load_config()
    return render_template("settings.html", config=config)


@app.route("/api/config", methods=["POST"])
def update_config():
    """Saves updated configuration from web interface."""
    data = request.get_json(silent=True) or {}
    webhook_url = clean_text(data.get("webhook_url", ""), 500)
    username = clean_text(data.get("username", ""), 80) or "smasher"
    avatar_url = clean_text(data.get("avatar_url", ""), 500) or DEFAULT_CONFIG["avatar_url"]

    if not is_valid_webhook_url(webhook_url):
        return jsonify({"status": "error", "message": "Invalid Discord Webhook URL"}), 400

    config = {
        "webhook_url": webhook_url,
        "username": username,
        "avatar_url": avatar_url,
    }
    save_config(config)
    return jsonify({"status": "success", "message": "Settings saved successfully!"})


@app.route("/api/send", methods=["POST"])
def send_webhook():
    """Handles posting messages to the Discord Webhook."""
    data = request.get_json(silent=True) or {}
    config = load_config()

    webhook_url = config.get("webhook_url")
    if not is_valid_webhook_url(webhook_url or ""):
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