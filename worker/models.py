import re
import uuid

from pydantic import BaseModel, Field, field_validator

STATES = {"CA", "NY", "TX", "FL", "GA", "PA", "MI", "WA", "IL", "OH"}


class FilingRequest(BaseModel):
    """Payload a client drops on the queue. Validated before we touch the browser,
    so bad data fails fast instead of halfway through a form."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    account: str = "default"

    company_name: str
    state: str
    email: str
    agent_name: str
    agent_address: str
    agent_zip: str

    @field_validator("company_name")
    @classmethod
    def must_be_llc(cls, v):
        v = " ".join(v.split())
        if not re.search(r"\b(LLC|L\.L\.C\.)$", v, re.I):
            raise ValueError("company name must end with LLC")
        return v

    @field_validator("state")
    @classmethod
    def known_state(cls, v):
        v = v.strip().upper()
        if v not in STATES:
            raise ValueError(f"unsupported state {v!r}")
        return v

    @field_validator("email")
    @classmethod
    def looks_like_email(cls, v):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}", v.strip()):
            raise ValueError("invalid email")
        return v.strip().lower()

    @field_validator("agent_zip")
    @classmethod
    def five_digit_zip(cls, v):
        v = v.strip()[:5]
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("zip must be 5 digits")
        return v
