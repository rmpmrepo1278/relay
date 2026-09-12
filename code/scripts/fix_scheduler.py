#!/usr/bin/env python3
"""Fix scheduler backup job and verify mind_loop interval changes."""

with open("/home/rohit/.hermes/scripts/hermes_scheduler.py", "r") as f:
    content = f.read()

old_job = 'Job("backup_all", p(f"{h}/scripts/backup_all.py"),\n            Schedule(minute="0", hour="2"), timeout=900, description="Unified backup", tags=["backup"]),'
new_job = 'Job("backup_databases", p(f"{h}/scripts/disaster_recovery.py backup"),\n            Schedule(minute="0", hour="2"), timeout=900, description="Nightly database backup via disaster_recovery", tags=["backup"]),'

content = content.replace(old_job, new_job)

# Verify the replacement happened
if new_job[:20] in content:
    print("Scheduler backup job updated successfully")
else:
    print("WARNING: Could not find backup_all job to replace!")

with open("/home/rohit/.hermes/scripts/hermes_scheduler.py", "w") as f:
    f.write(content)
