"""Tests for hermes_scheduler.py define_jobs"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_define_jobs_returns_list():
    """Test that define_jobs returns a list of Job objects."""
    from hermes_scheduler import define_jobs, Job
    jobs = define_jobs()
    assert isinstance(jobs, list), f"Expected list, got {type(jobs)}"
    assert len(jobs) > 0, "Expected at least one job"
    for job in jobs:
        assert isinstance(job, Job), f"Expected Job instance, got {type(job)}"
        assert hasattr(job, 'name'), f"Job missing 'name' attribute"
        assert hasattr(job, 'schedule'), f"Job missing 'schedule' attribute"
    print(f"PASS: define_jobs returned {len(jobs)} jobs")

def test_job_names_unique():
    """Test that all job names are unique."""
    from hermes_scheduler import define_jobs
    jobs = define_jobs()
    names = [job.name for job in jobs]
    assert len(names) == len(set(names)), f"Duplicate job names found"
    print(f"PASS: All {len(names)} job names are unique")

def test_all_jobs_have_schedule():
    """Test that all jobs have a valid schedule."""
    from hermes_scheduler import define_jobs
    jobs = define_jobs()
    for job in jobs:
        assert job.schedule is not None, f"Job {job.name} missing schedule"
    print(f"PASS: All {len(jobs)} jobs have schedules")

def test_known_jobs_present():
    """Test that known critical jobs exist."""
    from hermes_scheduler import define_jobs
    jobs = define_jobs()
    names = [job.name for job in jobs]
    critical = ['proactive_engine', 'mcp_health_watchdog', 'systemd_fix_watchdog', 'homelab_reporter', 'homelab_troubleshooter', 'homelab_deployer']
    for critical_job in critical:
        assert critical_job in names, f"Critical job {critical_job} not found"
    print(f"PASS: All critical jobs present")

if __name__ == '__main__':
    test_define_jobs_returns_list()
    test_job_names_unique()
    test_all_jobs_have_schedule()
    test_known_jobs_present()
    print('
All tests passed!')
