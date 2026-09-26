import pytest
from pydantic import ValidationError

from worker.models import FilingRequest

GOOD = dict(company_name="Acme Widgets  LLC", state="ca", email="Me@Acme.example",
            agent_name="Jo", agent_address="1 Main St", agent_zip="94105-1234")


def test_normalises_valid_payload():
    req = FilingRequest(**GOOD)
    assert req.company_name == "Acme Widgets LLC"
    assert req.state == "CA"
    assert req.email == "me@acme.example"
    assert req.agent_zip == "94105"
    assert req.job_id


@pytest.mark.parametrize("field,value", [
    ("company_name", "Acme Widgets Inc"),
    ("state", "ZZ"),
    ("email", "not-an-email"),
    ("agent_zip", "12ab5"),
])
def test_rejects_bad_fields(field, value):
    with pytest.raises(ValidationError):
        FilingRequest(**{**GOOD, field: value})
