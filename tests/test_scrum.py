from datetime import date, timedelta

import pytest

from integrationhub.demo import seed_demo
from integrationhub.scrum import Scrum, ScrumError
from integrationhub.store import Store


@pytest.fixture
def scrum(tmp_path):
    return Scrum(Store(tmp_path / "hub.db"))


def test_sprint_lifecycle_returns_unfinished_work_to_backlog(scrum):
    sid = scrum.create_sprint("Sprint 1", "2026-11-02", "2026-11-13", "Ship the connector")
    a = scrum.add_story("Connector", 3, sprint_id=sid)
    b = scrum.add_story("Mapping", 5, sprint_id=sid)
    scrum.start_sprint(sid)
    scrum.move_story(a, "done")
    assert scrum.progress(sid) == {"stories": 2, "done_stories": 1, "points": 8, "done_points": 3,
                                   "percent": 37.5}
    moved = scrum.close_sprint(sid)
    assert moved == 1
    assert [s["id"] for s in scrum.stories(backlog=True)] == [b]
    assert scrum.sprint(sid)["status"] == "closed"


def test_only_one_active_sprint(scrum):
    s1 = scrum.create_sprint("S1", "2026-11-02", "2026-11-13")
    s2 = scrum.create_sprint("S2", "2026-11-16", "2026-11-27")
    scrum.start_sprint(s1)
    with pytest.raises(ScrumError):
        scrum.start_sprint(s2)
    scrum.close_sprint(s1)
    with pytest.raises(ScrumError):
        scrum.start_sprint(s1)
    scrum.start_sprint(s2)
    assert scrum.active_sprint()["id"] == s2


def test_board_movement_is_clamped_to_the_columns(scrum):
    sid = scrum.create_sprint("S", "2026-11-02", "2026-11-13")
    story = scrum.add_story("Story", 2, sprint_id=sid)
    assert scrum.step_story(story, -1) == "todo"
    assert [scrum.step_story(story, +1) for _ in range(4)] == ["in_progress", "review", "done", "done"]
    assert scrum.story(story)["done_at"] is not None
    scrum.step_story(story, -1)
    assert scrum.story(story)["done_at"] is None


def test_external_key_prevents_duplicate_stories(scrum):
    assert scrum.add_story("Ticket 1", 3, source="helpdesk", external_key=501) is not None
    assert scrum.add_story("Ticket 1 again", 3, source="helpdesk", external_key=501) is None
    assert len(scrum.stories()) == 1


def test_validation(scrum):
    with pytest.raises(ScrumError):
        scrum.create_sprint("Bad", "2026-11-13", "2026-11-02")
    with pytest.raises(ScrumError):
        scrum.add_story("   ", 1)
    with pytest.raises(ScrumError):
        scrum.add_story("Negative", -2)


def test_burndown_tracks_done_points_and_ideal_line(scrum):
    today = date(2026, 11, 23)
    start = today - timedelta(days=4)
    seed_demo(scrum, today=today)
    sprint = scrum.active_sprint()
    assert sprint["start_date"] == start.isoformat()
    points = scrum.burndown(sprint["id"], today=today)
    assert len(points) == 14
    assert points[0].remaining == 21 and points[0].ideal == 21
    assert points[1].remaining == 16          # 5-point story done on day 1
    assert points[3].remaining == 13          # 3-point story done on day 3
    assert points[4].remaining == 13
    assert points[5].remaining is None        # the future is unknown
    assert points[-1].ideal == 0


def test_velocity_and_seed_is_idempotent(scrum):
    assert seed_demo(scrum) is True
    assert seed_demo(scrum) is False
    v = scrum.velocity()
    assert [x["status"] for x in v] == ["closed", "active"]
    assert v[0]["completed"] == 13
    assert len(scrum.stories(backlog=True)) == 4   # 3 backlog items + 1 unfinished from sprint 1
