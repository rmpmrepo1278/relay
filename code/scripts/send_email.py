import os, sys, json, base64

def main(argv):
    payload_path = argv[1] if len(argv) > 1 else "/tmp/email_payload.b64"
    with open(payload_path, "r") as f:
        raw = f.read().strip()
    try:
        payload = json.loads(base64.b64decode(raw))
    except Exception as e:
        print("EMAIL_BAD_PAYLOAD", str(e)[:120])
        return 1

    to = (payload.get("to") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "")
    if not to or "@" not in to:
        print("EMAIL_SKIP no-resolvable-recipient")
        return 0

    sys.path.insert(0, "/opt/data/scripts")
    import importlib.util
    spec = importlib.util.spec_from_file_location("ei", "/opt/data/scripts/email_intelligence.py")
    ei = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ei)

    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    try:
        svc = ei.get_gmail_service()
        msg = MIMEMultipart()
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        for f in payload.get("attachments", []):
            name = f.get("name", "attachment")
            data = base64.b64decode(f.get("content", ""))
            part = MIMEApplication(data, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=name)
            msg.attach(part)
        import googleapiclient
        r = svc.users().messages().send(
            userId="me",
            body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()},
        ).execute()
        print("EMAIL_SENT", r.get("id"), r.get("threadId"))
    except Exception as e:
        print("EMAIL_FAIL", type(e).__name__, str(e)[:240])
        return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
