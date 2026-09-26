"""Worker loop: claim a job, validate it, lock the account, drive the portal, report back.

    python -m worker.main
"""
import asyncio
import json
import logging
import os
import socket
import time
from pathlib import Path

import redis
from playwright.async_api import async_playwright
from pydantic import ValidationError

from . import store
from .flow import PortalError, run_filing
from .models import FilingRequest

log = logging.getLogger("rpa")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PORTAL_URL = os.environ.get("PORTAL_URL", "http://localhost:8000").rstrip("/")
ACCOUNTS = json.loads(os.environ.get("PORTAL_ACCOUNTS", '{"default": {"username": "demo", "password": "demo123"}}'))
HEADLESS = os.environ.get("HEADLESS", "1") != "0"
BROWSER_CHANNEL = os.environ.get("BROWSER_CHANNEL") or None   # e.g. "chrome" to use the system browser
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
ARTIFACTS = Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))
WORKER_ID = os.environ.get("WORKER_ID") or socket.gethostname()
PROCESSING = store.processing_key(WORKER_ID)


async def attempt(browser, req, status):
    context = await browser.new_context(viewport={"width": 1366, "height": 850}, locale="en-US")
    page = await context.new_page()
    page.set_default_timeout(20_000)
    try:
        return await run_filing(page, PORTAL_URL, ACCOUNTS[req.account], req, status)
    except Exception:
        ARTIFACTS.mkdir(exist_ok=True)
        shot = ARTIFACTS / f"{req.job_id}-{int(time.time())}.png"
        await page.screenshot(path=str(shot), full_page=True)
        log.info("saved screenshot %s", shot)
        raise
    finally:
        await context.close()


async def process(r, browser, raw):
    try:
        req = FilingRequest.model_validate_json(raw)
    except ValidationError as exc:
        job_id = json.loads(raw).get("job_id", "unknown")
        errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        store.JobStatus(r, job_id).set(state="invalid", error=errors)
        log.warning("job %s rejected: %s", job_id, errors)
        store.ack(r, PROCESSING, raw)
        return

    status = store.JobStatus(r, req.job_id)
    if req.account not in ACCOUNTS:
        status.set(state="invalid", error=f"unknown account {req.account}")
        store.ack(r, PROCESSING, raw)
        return

    token = store.acquire_lock(r, req.account)
    if not token:
        log.info("account %s is busy, putting job %s back", req.account, req.job_id)
        store.requeue(r, PROCESSING, raw)
        await asyncio.sleep(2)
        return

    try:
        for n in range(1, MAX_ATTEMPTS + 1):
            status.set(state="running", attempt=n)
            try:
                confirmation = await attempt(browser, req, status)
            except PortalError as exc:
                status.set(state="failed", error=str(exc))
                log.warning("job %s: portal rejected it: %s", req.job_id, exc)
                break
            except Exception as exc:  # timeouts, missing elements, crashed pages
                log.warning("job %s attempt %d failed: %s", req.job_id, n, exc)
                status.set(error=str(exc)[:300])
                if n == MAX_ATTEMPTS:
                    status.set(state="failed")
                continue
            status.set(state="done", confirmation=confirmation, error="")
            log.info("job %s filed, confirmation %s", req.job_id, confirmation)
            break
    finally:
        store.release_lock(r, req.account, token)
        store.ack(r, PROCESSING, raw)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # socket timeout has to be longer than the BLMOVE block time, otherwise an
    # idle queue looks like a dead connection (redis-py 8 defaults to 5s)
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=30,
                             health_check_interval=30)
    if moved := store.recover_stale(r, PROCESSING):
        log.info("recovered %d unfinished jobs", moved)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, channel=BROWSER_CHANNEL)
        log.info("worker %s up, waiting for jobs on %s", WORKER_ID, store.QUEUE)
        while True:
            try:
                raw = await asyncio.to_thread(store.claim, r, PROCESSING, 5)
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                log.warning("redis unavailable (%s), retrying in 3s", exc)
                await asyncio.sleep(3)
                continue
            if raw:
                await process(r, browser, raw)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
