import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
CONFIG_FILE = "config.json"


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
    data = request.json or {}
    webhook_url = data.get("webhook_url", "").strip()
    username = data.get("username", "").strip() or "smasher"
    avatar_url = (
        data.get("avatar_url", "").strip() or "https://i.imgur.com/4M34hi2.png"
    )

    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
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
    data = request.json or {}
    config = load_config()

    webhook_url = config.get("webhook_url")
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return jsonify({"status": "error", "message": "Webhook URL is not configured!"}), 400

    content = data.get("content", "").strip()
    image_url = data.get("image_url", "").strip()

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
    except Exception as e:
        return jsonify({"status": "error", "message": f"Unexpected Error: {e}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)