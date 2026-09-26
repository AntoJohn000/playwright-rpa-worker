"""A fake 'business filing' portal for the worker to automate.

Login -> company details -> registered agent -> review -> confirmation number.
Everything lives in memory. It is deliberately a bit annoying (optional random
slowness, server-side validation errors) so the worker has something real to handle.

    uvicorn demo_portal.app:app --port 8000
"""
import html
import os
import random
import re
import secrets
import time

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="Demo filing portal")

USERS = {os.environ.get("DEMO_USER", "demo"): os.environ.get("DEMO_PASS", "demo123")}
SLOW = os.environ.get("PORTAL_SLOW") == "1"
STATES = {"CA", "NY", "TX", "FL", "GA", "PA", "MI", "WA", "IL", "OH"}

sessions = {}   # sid -> {"user": ..., "filing": {...}}
filings = {}    # confirmation -> filing


def page(title, body, error=None):
    err = f'<div class="error" id="error">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html><head><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:560px;margin:40px auto}}
label{{display:block;margin-top:12px}} input,select{{width:100%;padding:6px}}
.error{{background:#fdd;padding:8px;margin:12px 0}} button{{margin-top:16px;padding:8px 16px}}</style>
</head><body><h1>{title}</h1>{err}{body}</body></html>""")


def current(request):
    return sessions.get(request.cookies.get("sid"))


def maybe_slow():
    if SLOW:
        time.sleep(random.uniform(0.5, 3))


@app.get("/")
def index():
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
def login_form(error: str = None):
    return page("Sign in", """
<form method="post" action="/login">
  <label>Username <input name="username" id="username"></label>
  <label>Password <input name="password" id="password" type="password"></label>
  <button id="sign-in">Sign in</button>
</form>""", error)


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    maybe_slow()
    if USERS.get(username) != password:
        return RedirectResponse("/login?error=Invalid+username+or+password", status_code=303)
    sid = secrets.token_hex(16)
    sessions[sid] = {"user": username, "filing": {}}
    resp = RedirectResponse("/filing/company", status_code=303)
    resp.set_cookie("sid", sid, httponly=True)
    return resp


@app.get("/filing/company")
def company_form(request: Request, error: str = None):
    if not current(request):
        return RedirectResponse("/login", status_code=303)
    options = "".join(f'<option value="{s}">{s}</option>' for s in sorted(STATES))
    return page("Step 1 of 3: Company", f"""
<form method="post">
  <label>Company name <input name="company_name" id="company_name"></label>
  <label>State <select name="state" id="state"><option value="">--</option>{options}</select></label>
  <label>Contact email <input name="email" id="email"></label>
  <button id="next">Continue</button>
</form>""", error)


@app.post("/filing/company")
def company_submit(request: Request, company_name: str = Form(""), state: str = Form(""),
                   email: str = Form("")):
    sess = current(request)
    if not sess:
        return RedirectResponse("/login", status_code=303)
    maybe_slow()
    if not re.search(r"\b(LLC|L\.L\.C\.)$", company_name.strip(), re.I):
        return RedirectResponse("/filing/company?error=Name+must+end+with+LLC", status_code=303)
    if state not in STATES:
        return RedirectResponse("/filing/company?error=Pick+a+state", status_code=303)
    sess["filing"].update(company_name=company_name.strip(), state=state, email=email)
    return RedirectResponse("/filing/agent", status_code=303)


@app.get("/filing/agent")
def agent_form(request: Request, error: str = None):
    if not current(request):
        return RedirectResponse("/login", status_code=303)
    return page("Step 2 of 3: Registered agent", """
<form method="post">
  <label>Agent name <input name="agent_name" id="agent_name"></label>
  <label>Street address <input name="agent_address" id="agent_address"></label>
  <label>ZIP <input name="agent_zip" id="agent_zip"></label>
  <button id="next">Continue</button>
</form>""", error)


@app.post("/filing/agent")
def agent_submit(request: Request, agent_name: str = Form(""), agent_address: str = Form(""),
                 agent_zip: str = Form("")):
    sess = current(request)
    if not sess:
        return RedirectResponse("/login", status_code=303)
    maybe_slow()
    if not re.fullmatch(r"\d{5}", agent_zip):
        return RedirectResponse("/filing/agent?error=ZIP+must+be+5+digits", status_code=303)
    sess["filing"].update(agent_name=agent_name, agent_address=agent_address, agent_zip=agent_zip)
    return RedirectResponse("/filing/review", status_code=303)


@app.get("/filing/review")
def review(request: Request):
    sess = current(request)
    if not sess:
        return RedirectResponse("/login", status_code=303)
    rows = "".join(f"<tr><th>{k}</th><td>{html.escape(str(v))}</td></tr>" for k, v in sess["filing"].items())
    return page("Step 3 of 3: Review", f"""
<table id="summary">{rows}</table>
<form method="post" action="/filing/submit"><button id="submit">Submit filing</button></form>""")


@app.post("/filing/submit")
def submit(request: Request):
    sess = current(request)
    if not sess:
        return RedirectResponse("/login", status_code=303)
    maybe_slow()
    number = f"DOC-{random.randint(100000, 999999)}"
    filings[number] = dict(sess["filing"])
    sess["filing"] = {}
    return page("Filing received", f'<p>Your confirmation number is <strong id="confirmation">{number}</strong></p>')


@app.get("/api/filings/{number}")
def get_filing(number: str):
    return filings.get(number) or {"error": "not found"}
