from __future__ import annotations

import csv
import io
from datetime import date

from openitems.domain import engagements, policies, policy_export
from openitems.domain.policies import PolicyInput
from openitems.domain.policy_export import EXPORT_HEADERS


def _engagement(session, name: str = "Acme"):
    return engagements.create(session, name)


def test_export_headers_lead_with_id(session):
    e = _engagement(session)
    csv_text = policy_export.to_csv_text(policies.list_for(session, e))
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header[0] == "id"
    assert tuple(header) == EXPORT_HEADERS


def test_export_serializes_dates_iso(session):
    e = _engagement(session)
    policies.create(
        session,
        e,
        PolicyInput(
            name="Main GL",
            carrier="Travelers",
            coverage="GL",
            policy_number="GL-9001",
            effective_date=date(2026, 1, 1),
            expiration_date=date(2027, 1, 1),
        ),
    )
    rows = list(csv.reader(io.StringIO(policy_export.to_csv_text(policies.list_for(session, e)))))
    assert rows[1][5] == "2026-01-01"
    assert rows[1][6] == "2027-01-01"


def test_export_blanks_for_none_dates(session):
    e = _engagement(session)
    policies.create(
        session,
        e,
        PolicyInput(name="Cyber", coverage="Cyber"),
    )
    rows = list(csv.reader(io.StringIO(policy_export.to_csv_text(policies.list_for(session, e)))))
    assert rows[1][5] == ""
    assert rows[1][6] == ""


def test_export_quotes_embedded_commas_and_quotes(session):
    """csv.writer must quote fields with delimiters and double-up embedded
    quotes so the file survives a round-trip through Excel and back."""
    e = _engagement(session)
    policies.create(
        session,
        e,
        PolicyInput(
            name='Re: "high-deductible" plan, 2026',
            description="primary, with rider",
        ),
    )
    text = policy_export.to_csv_text(policies.list_for(session, e))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1][1] == 'Re: "high-deductible" plan, 2026'
    assert rows[1][8] == "primary, with rider"


def test_write_to_creates_parents(tmp_path, session):
    e = _engagement(session)
    policies.create(session, e, PolicyInput(name="P"))
    target = tmp_path / "nested" / "subdir" / "out.csv"
    written = policy_export.write_to(target, policies.list_for(session, e))
    assert written == target
    assert target.exists()
    assert target.read_text(encoding="utf-8-sig").startswith("id,")
