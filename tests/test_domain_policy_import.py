from __future__ import annotations

from datetime import date

import pytest

from openitems.domain import engagements, policies, policy_import
from openitems.domain.policies import PolicyInput
from openitems.domain.policy_import import ImportFileError


def _engagement(session, name: str = "Acme"):
    return engagements.create(session, name)


def _csv(*rows: str) -> list[str]:
    """Header + arbitrary data rows."""
    return [
        "name,carrier,coverage,policy_number,effective_date,expiration_date,location,description",
        *rows,
    ]


def test_preview_happy_path_classifies_all_new(session):
    e = _engagement(session)
    lines = _csv(
        "Main GL,Travelers,GL,GL-9001,2026-01-01,2027-01-01,HQ,Primary",
        "WC,Hartford,WC,WC-44210,2026-03-15,2027-03-14,,",
        "Cyber rider,,Cyber,,,,,Pending broker",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.new_count == 3
    assert pre.duplicate_count == 0
    assert pre.error_count == 0
    statuses = [r.status for r in pre.rows]
    assert statuses == ["new", "new", "new"]
    # Date parsing populated correctly
    first = pre.rows[0]
    assert first.input is not None
    assert first.input.effective_date == date(2026, 1, 1)
    assert first.input.expiration_date == date(2027, 1, 1)


def test_preview_skips_existing_dedup_key(session):
    e = _engagement(session)
    policies.create(
        session,
        e,
        PolicyInput(name="Pre-existing GL", carrier="Travelers", policy_number="GL-9001"),
    )
    lines = _csv(
        "Main GL,Travelers,GL,GL-9001,,,,",
        "Brand new,Hartford,WC,WC-1,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert [r.status for r in pre.rows] == ["duplicate", "new"]
    assert "Already exists" in pre.rows[0].message


def test_preview_dedup_is_case_insensitive_and_ignores_whitespace(session):
    e = _engagement(session)
    policies.create(
        session,
        e,
        PolicyInput(name="Pre", carrier="Travelers", policy_number="GL-9001"),
    )
    lines = _csv(
        "Main, travelers ,GL, gl-9001 ,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "duplicate"


def test_preview_intra_csv_dedup(session):
    e = _engagement(session)
    lines = _csv(
        "First,Travelers,GL,GL-9001,,,,",
        "Second copy,Travelers,GL,GL-9001,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert [r.status for r in pre.rows] == ["new", "duplicate"]
    assert "earlier row" in pre.rows[1].message


def test_preview_blank_dedup_key_never_dedupes(session):
    e = _engagement(session)
    lines = _csv(
        "Blank A,,GL,,,,,",
        "Blank B,,GL,,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert [r.status for r in pre.rows] == ["new", "new"]


def test_preview_bad_date_classifies_as_error(session):
    e = _engagement(session)
    lines = _csv(
        "Bad date,Travelers,GL,GL-9001,not-a-date,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "error"
    assert "effective_date" in pre.rows[0].message


def test_preview_effective_after_expiration_is_error(session):
    e = _engagement(session)
    lines = _csv(
        "Backwards,Travelers,GL,GL-9001,2027-01-01,2026-01-01,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "error"
    assert "after expiration" in pre.rows[0].message


def test_preview_blank_name_is_error(session):
    e = _engagement(session)
    lines = _csv(
        ",Travelers,GL,GL-9001,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "error"
    assert "'name'" in pre.rows[0].message


def test_preview_unknown_columns_are_collected_not_errors(session):
    e = _engagement(session)
    lines = [
        "name,carrier,extra_thing,id,policy_number",
        "Main GL,Travelers,whatever,deadbeef,GL-1",
    ]
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "new"
    assert "extra_thing" in pre.unknown_columns
    # 'id' is silently ignored, never reported as unknown
    assert "id" not in [c.lower() for c in pre.unknown_columns]


def test_preview_missing_optional_columns_defaults_to_blank(session):
    e = _engagement(session)
    lines = [
        "name,carrier",
        "Main GL,Travelers",
    ]
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "new"
    assert pre.rows[0].input is not None
    assert pre.rows[0].input.coverage == ""
    assert pre.rows[0].input.effective_date is None


def test_missing_required_name_column_raises(session):
    e = _engagement(session)
    lines = ["carrier,policy_number", "Travelers,GL-1"]
    with pytest.raises(ImportFileError):
        policy_import.from_iterable(session, e, lines)


def test_commit_inserts_new_rows_and_returns_summary(session):
    e = _engagement(session)
    policies.create(
        session, e, PolicyInput(name="Pre", carrier="Travelers", policy_number="GL-9001")
    )
    lines = _csv(
        "Dup,Travelers,GL,GL-9001,,,,",
        "Bad,Travelers,GL,GL-2,not-a-date,,,",
        "New A,Hartford,WC,WC-1,,,,",
        "New B,Liberty,Auto,AUTO-1,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    result = policy_import.commit(session, e, pre)
    assert result.imported == 2
    assert result.skipped_duplicates == 1
    assert result.errors == 1
    assert any("Line 3" in m for m in result.error_messages)

    after = policies.list_for(session, e)
    names = sorted(p.name for p in after)
    assert names == ["New A", "New B", "Pre"]


def test_commit_is_idempotent(session):
    e = _engagement(session)
    lines = _csv(
        "Main GL,Travelers,GL,GL-9001,,,,",
        "WC,Hartford,WC,WC-1,,,,",
    )
    pre1 = policy_import.from_iterable(session, e, lines)
    r1 = policy_import.commit(session, e, pre1)
    assert r1.imported == 2

    pre2 = policy_import.from_iterable(session, e, lines)
    r2 = policy_import.commit(session, e, pre2)
    assert r2.imported == 0
    assert r2.skipped_duplicates == 2
    assert len(policies.list_for(session, e)) == 2


def test_template_csv_classifies_all_new_against_empty_engagement(session, tmp_path):
    e = _engagement(session)
    template = policy_import.template_path()
    assert template.exists(), "Bundled template CSV is missing."
    pre = policy_import.preview(session, e, template)
    # Header drift would surface here — if a column is renamed without updating
    # the template, the row stops classifying as `new`.
    assert pre.error_count == 0, [r.message for r in pre.rows if r.status == "error"]
    assert pre.duplicate_count == 0
    assert pre.new_count == len(pre.rows) >= 1


def test_preview_missing_file_raises(tmp_path, session):
    e = _engagement(session)
    with pytest.raises(ImportFileError):
        policy_import.preview(session, e, tmp_path / "does-not-exist.csv")


def test_preview_handles_multiline_quoted_cells(session, tmp_path):
    """A description with embedded newlines (common from Excel paste) must
    parse as a single field, not split the row apart."""
    e = _engagement(session)
    csv_text = (
        "name,carrier,coverage,policy_number,effective_date,expiration_date,location,description\n"
        'Main GL,Travelers,GL,GL-1,,,,"line one\nline two\nline three"\n'
        "Second,Hartford,WC,WC-2,,,,single-line\n"
    )
    path = tmp_path / "multiline.csv"
    path.write_text(csv_text, encoding="utf-8")
    pre = policy_import.preview(session, e, path)
    assert [r.status for r in pre.rows] == ["new", "new"]
    assert pre.rows[0].input is not None
    assert pre.rows[0].input.description == "line one\nline two\nline three"
    # Line numbers reflect physical lines so users can find the row in their editor:
    # row 1 spans physical lines 2–4, row 2 sits on physical line 5.
    assert pre.rows[0].line == 4
    assert pre.rows[1].line == 5


def test_preview_normalizes_raw_dict_keys_for_uppercase_headers(session):
    """Error rows fall back to row.raw for display; the keys must be the
    canonical lowercase names so the wizard's lookup hits, regardless of the
    casing the user used in their CSV header."""
    e = _engagement(session)
    lines = [
        "Name,Carrier,Policy_Number,Effective_Date",
        "Bad,Travelers,GL-1,not-a-date",
    ]
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "error"
    assert pre.rows[0].raw["name"] == "Bad"
    assert pre.rows[0].raw["carrier"] == "Travelers"
    assert pre.rows[0].raw["effective_date"] == "not-a-date"
