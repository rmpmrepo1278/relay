#!/usr/bin/env python3
"""email_drop.py — record + follow-up + best-effort email-drop for a generated application.

Invoked by run_apply.sh after career-ops auto_pipeline.py runs. Inputs:
  argv[1]: base64(job_json)     {url, company, title, score}
  argv[2]: base64(result_json)  {report_path, resume_path, cover_path, company_slug}

Behavior (ALWAYS): record the application (status=applied) + schedule a 14-day
follow-up in applications.db.
EMAIL Drop (best-effort, gated by EMAIL_DROP=1): send a lightweight outreach email
WITH attachments (resume + cover letter PDFs) ONLY when a resolver finds an
EXPLICIT recruiter address. Never guess-send to arbitrary addresses.
"""
import sys, os, json, base64, subprocess, pathlib, tempfile

CAREER_OPS = pathlib.Path("/home/rohit/projects/career-ops")
TRACKER = CAREER_OPS / "tracker.py"
CONTACT_MAP_FILE = pathlib.Path("/home/rohit/.hermes/scripts/recruiting_contacts.json")
HERMES_CONTAINER = "hermes"
CONTAINER_B64 = "/tmp/email_payload.b64"

spec = None
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("tracker", str(TRACKER))
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
except Exception as e:
    tr = None
    print("[record] ERROR importing tracker: %s" % e, file=sys.stderr)


def b64json(arg):
    if not arg:
        return {}
    try:
        return json.loads(base64.b64decode(arg))
    except Exception:
        return {}


def normalize_company(name):
    n = (name or "").strip()
    for suffix in [" llc", " inc", " corp", " corporation", " ltd", " technologies",
                   " systems", " group", " software", " labs", " laboratories",
                   " holding", " holdings", " limited", " plc", " gmbh", " ag",
                   " llp", " co", " company", " usa", " us"]:
        if n.lower().endswith(suffix):
            n = n[:-len(suffix)]
    return n.strip()


def load_contacts():
    if CONTACT_MAP_FILE.exists():
        try:
            return json.loads(CONTACT_MAP_FILE.read_text())
        except Exception:
            return {}
    return {}


def resolve_recipient(company):
    contacts = load_contacts()
    norm = normalize_company(company).lower().replace(".", "")
    entries = contacts.get("companies", {})
    if norm in entries:
        return entries[norm], "explicit"
    if company in entries:
        return entries[company], "explicit"
    if contacts.get("fallback_guess") is not False:
        domain = norm.replace(" ", "").lower()
        if len(domain) >= 2 and domain.isalnum():
            cand = f"{contacts.get('default_prefix', 'careers')}@{domain}.com"
            return cand, "guess"
    return None, None


def main():
    job = b64json(sys.argv[1] if len(sys.argv) > 1 else "")
    res = b64json(sys.argv[2] if len(sys.argv) > 2 else "")

    company = job.get("company", "")
    title = job.get("title", "")
    url = job.get("url", "")
    score = job.get("score", 0)
    report_path = res.get("report_path", "")
    resume_path = res.get("resume_path", "")
    cover_path = res.get("cover_path", "")

    # 1) ALWAYS record + schedule follow-up
    if tr is not None and company and title:
        try:
            app_id = tr.track_application(
                company=company, title=title, url=url, score=float(score or 0),
                status="applied", jd_snippet="",
                report_path=report_path, resume_path=resume_path,
                cover_letter_path=cover_path,
            )
            tr.schedule_follow_up(app_id, days=14)
            print("[record] app_id=%s status=applied +followup(14d)" % app_id)
            _LAST_APP_ID = app_id
        except Exception as e:
            print("[record] ERROR: %s" % e, file=sys.stderr)
    else:
        print("[record] skipped (no tracker/company/title)")

    # 2) Best-effort email drop
    if os.environ.get("EMAIL_DROP", "1") != "1":
        print("[email] disabled (EMAIL_DROP!=1)")
        return
    to, conf = resolve_recipient(company)
    if conf != "explicit":
        print("[email] SKIP %s (%s) — add explicit address in recruiting_contacts.json" % ((to or "none"), conf or "no-contact"))
        return

    subject = f"Application — {title}"
    body = (
        f"Hi {company} Talent Team,\n\n"
        f"I'm submitting my application for the {title} role.\n\n"
        f"I'm a Technical Program Management leader with 20+ years across enterprise "
        f"transformation, ERP modernization, and portfolio/delivery leadership, including "
        f"T-Mobile and Microsoft.\n\n"
        f"My resume and a tailored cover letter are attached." +
        (f"\n\nJob reference: {url}" if url else "") +
        "\n\nThank you,\nRohit Mishra\n(425) 786-8016 | rohitmishra1278@gmail.com | linkedin.com/in/rohitmishra4"
    )
    attachments = []
    for path, name in [(resume_path, "Rohit_Mishra_Resume.pdf"), (cover_path, "Rohit_Mishra_Cover_Letter.pdf")]:
        if path and os.path.exists(path):
            data = pathlib.Path(path).read_bytes()
            attachments.append({"name": name, "content": base64.b64encode(data).decode()})

    payload = {"to": to, "subject": subject, "body": body, "attachments": attachments}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()

    # write payload to a shared tmp, docker cp into container, docker exec sender
    host_tmp = tempfile.mktemp(suffix=".b64", prefix="email_")
    pathlib.Path(host_tmp).write_text(b64)
    try:
        subprocess.run(["docker", "cp", host_tmp, f"{HERMES_CONTAINER}:{CONTAINER_B64}"],
                       check=True, capture_output=True, timeout=30)
        r = subprocess.run(
            ["docker", "exec", HERMES_CONTAINER, "env", "HOME=/opt/data",
             "/opt/hermes/.venv/bin/python3", "/opt/data/scripts/send_email.py", CONTAINER_B64],
            capture_output=True, text=True, timeout=120)
        print("[email] to=%s rc=%s" % (to, r.returncode))
        tail = (r.stdout or "").strip().splitlines() or (r.stderr or "").strip().splitlines()
        if tail:
            print("[email] " + tail[-1])
        if r.returncode == 0 and _LAST_APP_ID and tr is not None:
            try:
                conn = tr.get_conn()
                conn.execute("UPDATE applications SET notes=?, updated_at=datetime('now') WHERE id=?",
                             (f"recruiter={to}", _LAST_APP_ID))
                conn.commit()
                print("[record] stored recipient in notes")
            except Exception as _e:
                print("[records] notes update failed: %s" % _e, file=sys.stderr)
        if r.returncode != 0:
            print("[email] FAILED \u2014 surface for manual review")

    except Exception as e:
        print("[email] ERROR: %s" % e, file=sys.stderr)
    finally:
        try:
            os.remove(host_tmp)
        except Exception:
            pass


if __name__ == "__main__":
    main()
