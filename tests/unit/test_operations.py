from pathlib import Path

from career_agent.operations.worker import Operations, configure_scheduler

ROOT = Path(__file__).resolve().parents[2]


def test_schedule_and_defaults_are_safe():
    ops = Operations.load(ROOT)
    assert not ops.email_sync_enabled and not ops.calendar_write_enabled and not ops.use_ai
    scheduler = configure_scheduler(ROOT)
    jobs = scheduler.get_jobs()
    assert {j.id for j in jobs} == {"discovery", "summary"}
    assert "9,21" in str(next(j.trigger for j in jobs if j.id == "discovery"))
    assert str(scheduler.timezone) == "America/New_York"
