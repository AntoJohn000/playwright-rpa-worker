import json

import fakeredis
import pytest

from worker import store


PROC = store.processing_key("w1")


@pytest.fixture
def r():
    return fakeredis.FakeRedis(decode_responses=True)


def test_claim_moves_job_to_processing(r):
    store.enqueue(r, {"job_id": "a"})
    raw = store.claim(r, PROC, timeout=1)
    assert json.loads(raw)["job_id"] == "a"
    assert r.llen(store.QUEUE) == 0
    assert r.llen(PROC) == 1
    store.ack(r, PROC, raw)
    assert r.llen(PROC) == 0


def test_jobs_come_out_in_order(r):
    for i in range(3):
        store.enqueue(r, {"job_id": str(i)})
    assert [json.loads(store.claim(r, PROC, 1))["job_id"] for _ in range(3)] == ["0", "1", "2"]


def test_recover_stale_puts_jobs_back(r):
    store.enqueue(r, {"job_id": "a"})
    store.claim(r, PROC, 1)  # worker "crashes" here
    assert store.recover_stale(r, PROC) == 1
    assert r.llen(store.QUEUE) == 1


def test_recover_leaves_other_workers_alone(r):
    store.enqueue(r, {"job_id": "a"})
    store.claim(r, store.processing_key("w2"), 1)  # w2 is still working on it
    assert store.recover_stale(r, PROC) == 0
    assert r.llen(store.processing_key("w2")) == 1


def test_lock_is_exclusive_and_owner_only(r):
    token = store.acquire_lock(r, "acct")
    assert token
    assert store.acquire_lock(r, "acct") is None
    assert store.release_lock(r, "acct", "someone-else") == 0
    assert store.release_lock(r, "acct", token) == 1
    assert store.acquire_lock(r, "acct")


def test_step_timings_recorded(r):
    status = store.JobStatus(r, "job1")
    with status.step("login"):
        pass
    with pytest.raises(RuntimeError):
        with status.step("submit"):
            raise RuntimeError("button missing")
    steps = json.loads(r.hget(store.JOB_KEY.format("job1"), "steps"))
    assert [(s["step"], s["ok"]) for s in steps] == [("login", True), ("submit", False)]
    assert steps[1]["error"] == "button missing"
