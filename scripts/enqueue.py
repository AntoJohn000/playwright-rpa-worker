"""Drop sample jobs on the queue and watch them finish.

    python scripts/enqueue.py            # one valid job
    python scripts/enqueue.py --bad      # plus one that fails validation
"""
import argparse
import os
import sys
import time

import redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from worker import store  # noqa: E402
from worker.models import FilingRequest  # noqa: E402

SAMPLE = {
    "company_name": "Blue Harbor Coffee LLC",
    "state": "CA",
    "email": "owner@blueharbor.example",
    "agent_name": "Maria Lopez",
    "agent_address": "221 Market St, San Francisco",
    "agent_zip": "94105",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bad", action="store_true", help="also send an invalid job")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

    jobs = [FilingRequest(**SAMPLE).model_dump() for _ in range(args.count)]
    if args.bad:
        jobs.append({**SAMPLE, "job_id": "bad-zip-job", "company_name": "No Suffix Inc", "agent_zip": "9410"})
    for job in jobs:
        store.enqueue(r, job)
        print("queued", job["job_id"])

    pending = {j["job_id"] for j in jobs}
    deadline = time.time() + 120
    while pending and time.time() < deadline:
        for job_id in list(pending):
            st = r.hgetall(store.JOB_KEY.format(job_id))
            if st.get("state") in ("done", "failed", "invalid"):
                print(job_id, st.get("state"), st.get("confirmation") or st.get("error"), st.get("steps", ""))
                pending.discard(job_id)
        time.sleep(1)
    if pending:
        print("still waiting on", ", ".join(pending))


if __name__ == "__main__":
    main()
