import sys, json, urllib.request, urllib.error, uuid
sys.path.insert(0, "/home/rohit/.hermes/scripts")
from n8n_bridge_server import TELEGRAM_TOKEN, TELEGRAM_CHAT

CHAT = TELEGRAM_CHAT
cands = [7338, 10000, 10005, 10023, 10024, 10025, 10026, 10027, 10028, 10030, 10031, 10122, 10127, 10128]


def send(payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        if r.get("ok"):
            return f"EXISTS msg_id={r['result']['message_id']}"
        return f"api ok=False {str(r.get('description', r.get('error_code', '?')))[:40]}"
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            return f"{body.get('description', 'HTTP %d' % e.code)[:55]}"
        except Exception:
            return f"HTTP {e.code}"
    except Exception as e:
        return f"ERR {str(e)[:40]}"


for tid in cands:
    payload = {"chat_id": str(CHAT), "text": "probe-" + str(uuid.uuid4())[:6], "message_thread_id": tid}
    print(f"thread {tid}: {send(payload)}")

payload = {"chat_id": str(CHAT), "text": "probe-" + str(uuid.uuid4())[:6]}
print(f"General(no tid): {send(payload)}")