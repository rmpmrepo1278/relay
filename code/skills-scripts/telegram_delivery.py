import os
import httpx

def send_to_telegram(file_path: str) -> str:
    """Sends a specific file from the homelab directly to the user's Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL") # Default home channel
    
    if not token or not chat_id:
        return "Error: Telegram credentials (TOKEN/HOME_CHANNEL) not found in environment."
    if not os.path.exists(file_path):
        return f"Error: File {file_path} not found."

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {"document": (os.path.basename(file_path), f)}
            data = {"chat_id": chat_id}
            resp = httpx.post(url, data=data, files=files, timeout=30.0)
            if resp.status_code == 200:
                return f"✅ Successfully sent {os.path.basename(file_path)} to Telegram."
            else:
                return f"❌ Failed to send: {resp.text}"
    except Exception as e:
        return f"Error delivering file: {str(e)}"
