"""Redis plumbing: a reliable queue, per-account locks and per-job status."""
import json
import time
import uuid
from contextlib import contextmanager

QUEUE = "rpa:queue"
PROCESSING = "rpa:processing:{}"   # one list per worker
JOB_KEY = "rpa:job:{}"
LOCK_KEY = "rpa:lock:{}"

# delete the lock only if we still own it (it may have expired and been re-taken)
RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def enqueue(r, payload: dict):
    r.lpush(QUEUE, json.dumps(payload))


def processing_key(worker_id):
    return PROCESSING.format(worker_id)


def claim(r, processing, timeout=5):
    """Move one job from the queue to this worker's processing list atomically.

    If the worker dies mid-job the payload is still sitting in its processing
    list, so `recover_stale` can put it back instead of losing it.
    """
    return r.blmove(QUEUE, processing, timeout, "RIGHT", "LEFT")


def ack(r, processing, raw):
    r.lrem(processing, 1, raw)


def requeue(r, processing, raw):
    pipe = r.pipeline()
    pipe.lrem(processing, 1, raw)
    pipe.lpush(QUEUE, raw)
    pipe.execute()


def recover_stale(r, processing):
    """On startup, push whatever this worker was holding when it died back onto the queue.

    Only our own list: touching another worker's list could requeue a job it is
    still running and file it twice.
    """
    moved = 0
    while r.lmove(processing, QUEUE, "RIGHT", "LEFT"):
        moved += 1
    return moved


def acquire_lock(r, name, ttl_ms=10 * 60 * 1000):
    """One job per portal account at a time. Two browsers logged into the same
    account step on each other's session/cart, so the second one has to wait."""
    token = uuid.uuid4().hex
    if r.set(LOCK_KEY.format(name), token, nx=True, px=ttl_ms):
        return token
    return None


def release_lock(r, name, token):
    return r.eval(RELEASE_LOCK, 1, LOCK_KEY.format(name), token)


class JobStatus:
    """Status hash the client can poll: state, error, result and per-step timings."""

    def __init__(self, r, job_id, ttl=7 * 24 * 3600):
        self.r = r
        self.key = JOB_KEY.format(job_id)
        self.ttl = ttl
        self.steps = []

    def set(self, **fields):
        fields["updated_at"] = time.time()
        self.r.hset(self.key, mapping={k: str(v) for k, v in fields.items()})
        self.r.expire(self.key, self.ttl)

    @contextmanager
    def step(self, name):
        started = time.perf_counter()
        self.set(state="running", current_step=name)
        try:
            yield
        except Exception as exc:
            self.steps.append({"step": name, "ok": False, "secs": round(time.perf_counter() - started, 2),
                               "error": str(exc)[:200]})
            raise
        else:
            self.steps.append({"step": name, "ok": True, "secs": round(time.perf_counter() - started, 2)})
        finally:
            self.set(steps=json.dumps(self.steps))

    def get(self):
        return self.r.hgetall(self.key)
