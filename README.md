# playwright-rpa-worker

A queue-driven browser automation worker, the kind of setup I use for form-filing RPA: jobs land in Redis, workers pick them up, drive a web portal with Playwright and report back step by step.

It ships with a small fake "business filing" portal (`demo_portal/`) so the whole thing runs locally: log in → company details → registered agent → review → confirmation number.

## What it handles

- **Validation before the browser opens**: payloads are checked with Pydantic (LLC suffix, state, email, ZIP). Bad jobs fail in milliseconds with a clear error instead of halfway through a form.
- **Reliable queue**: `BLMOVE` moves a job into the worker's own processing list, so a crashed worker's job gets requeued on restart instead of lost. Each worker only recovers its own list, so a restart never requeues a job another worker is still running (which would mean filing it twice).
- **One session per account**: a Redis lock (`SET NX PX` + owner-checked release in Lua) makes sure two workers never log into the same portal account at once. If the account is busy, the job goes back on the queue.
- **Step-level status**: every job has a status hash with state, attempt, error, confirmation and timings for each step, so you can see exactly where a run broke.
- **Retries with a clean browser context**: timeouts and flaky pages are retried; errors the portal shows us (bad data) are not. Failures save a full-page screenshot to `artifacts/`.
- **Review check before submitting**: the worker compares the review page against the payload before it clicks submit.

## Run it

```bash
docker compose up --build        # redis + demo portal + 2 workers
python scripts/enqueue.py --count 3 --bad
```

Output (two workers, one shared account):

```
queued 1fc76301c946
queued a7334dec4fdf
queued 154e226683d5
queued bad-zip-job
bad-zip-job invalid company_name: Value error, company name must end with LLC; agent_zip: Value error, zip must be 5 digits
1fc76301c946 done DOC-365259 [{"step": "login", "ok": true, "secs": 2.29}, {"step": "company", "ok": true, "secs": 2.25}, ...]
154e226683d5 done DOC-309440 [...]
a7334dec4fdf done DOC-100097 [...]
```

and in the worker logs you can see the account lock doing its job:

```
worker-2  | job 1fc76301c946 filed, confirmation DOC-365259
worker-1  | account default is busy, putting job a7334dec4fdf back
```

### Without Docker

```bash
pip install -r requirements-dev.txt
playwright install chromium           # or set BROWSER_CHANNEL=chrome to use your installed Chrome
docker run -d -p 6379:6379 redis:7-alpine

uvicorn demo_portal.app:app --port 8000
python -m worker.main
python scripts/enqueue.py
```

## Config

| Env var | Default | |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `PORTAL_URL` | `http://localhost:8000` | |
| `PORTAL_ACCOUNTS` | `{"default": {"username": "demo", "password": "demo123"}}` | JSON map of account name → login |
| `MAX_ATTEMPTS` | `3` | retries per job |
| `HEADLESS` | `1` | `0` to watch the browser |
| `BROWSER_CHANNEL` | bundled Chromium | e.g. `chrome` |
| `WORKER_ID` | hostname | names this worker's processing list |
| `PORTAL_SLOW` | off | portal only: random 0.5–3s delays |

## Layout

```
worker/
  models.py   payload validation
  store.py    queue, locks, job status
  flow.py     the Playwright steps
  main.py     worker loop, retries, screenshots
demo_portal/  fake portal (FastAPI)
scripts/      enqueue sample jobs and watch them
tests/        unit tests (fakeredis)
```

## Tests

```bash
pytest
```

## License

MIT
