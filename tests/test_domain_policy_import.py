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
        # Blank id keeps this on the insert path; the round-trip behaviour
        # of a populated id has its own dedicated test below.
        "Main GL,Travelers,whatever,,GL-1",
    ]
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "new"
    assert "extra_thing" in pre.unknown_columns
    # 'id' is treated as a structural column, not surfaced as unknown.
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


def test_preview_decodes_cp1252_when_utf8_fails(session, tmp_path):
    """Excel-on-Windows saves CSVs as cp1252 by default. The importer should
    accept that without forcing the user to re-save."""
    e = _engagement(session)
    # Build the payload as bytes so the cp1252-only bytes (0x87, 0x92) survive.
    # 0x92 is the cp1252 right single quote; that byte sequence is invalid
    # as UTF-8, so utf-8-sig will fail and cp1252 will succeed.
    header = (
        b"name,carrier,coverage,policy_number,"
        b"effective_date,expiration_date,location,description\n"
    )
    body = b"Fran\x87ois,Travelers,GL,GL-1,,,,Curly\x92quote\n"
    path = tmp_path / "cp1252.csv"
    path.write_bytes(header + body)
    pre = policy_import.preview(session, e, path)
    assert pre.rows[0].status == "new"
    assert pre.rows[0].input is not None
    # The smart quote round-trips as the proper unicode codepoint (U+2019,
    # RIGHT SINGLE QUOTATION MARK), not mojibake. Written as a \u escape so
    # the literal character doesn't trip RUF001 in the source.
    assert "\u2019" in pre.rows[0].input.description


def test_preview_handles_utf8_bom(session, tmp_path):
    """Excel's 'CSV UTF-8' export prepends a BOM. utf-8-sig must strip it."""
    e = _engagement(session)
    csv_text = (
        "name,carrier,policy_number\n"
        "Main GL,Travelers,GL-9001\n"
    )
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + csv_text.encode("utf-8"))
    pre = policy_import.preview(session, e, path)
    # If the BOM weren't stripped, the first column key would be "﻿name"
    # and the required-column check would raise ImportFileError.
    assert pre.rows[0].status == "new"
    assert pre.rows[0].input.name == "Main GL"


def test_preview_handles_crlf_line_endings(session, tmp_path):
    """Files exported on Windows use CRLF; csv.reader on a StringIO must treat
    the CR as part of the line terminator, not as content."""
    e = _engagement(session)
    csv_text = (
        "name,carrier,policy_number\r\n"
        "Main GL,Travelers,GL-9001\r\n"
        "WC,Hartford,WC-1\r\n"
    )
    path = tmp_path / "crlf.csv"
    path.write_bytes(csv_text.encode("utf-8"))
    pre = policy_import.preview(session, e, path)
    assert [r.status for r in pre.rows] == ["new", "new"]
    # No stray '\r' contamination in the parsed values.
    assert pre.rows[0].input.policy_number == "GL-9001"


def test_preview_sniffs_semicolon_delimiter(session, tmp_path):
    """European Excel exports use ';' as the field separator. csv.Sniffer
    should detect this without configuration."""
    e = _engagement(session)
    csv_text = (
        "name;carrier;coverage;policy_number;effective_date;expiration_date\n"
        "Main GL;Travelers;GL;GL-9001;2026-01-01;2027-01-01\n"
        "WC;Hartford;WC;WC-1;;\n"
    )
    path = tmp_path / "semicolon.csv"
    path.write_text(csv_text, encoding="utf-8")
    pre = policy_import.preview(session, e, path)
    assert [r.status for r in pre.rows] == ["new", "new"]
    assert pre.rows[0].input.carrier == "Travelers"
    assert pre.rows[0].input.policy_number == "GL-9001"


def test_preview_handles_quoted_embedded_commas(session):
    """Carrier names with commas (`Smith, Jones & Co.`) must round-trip when
    properly quoted, not split into separate columns."""
    e = _engagement(session)
    lines = _csv(
        '"Main GL","Smith, Jones & Co.",GL,GL-1,,,,',
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.rows[0].status == "new"
    assert pre.rows[0].input.carrier == "Smith, Jones & Co."


def test_preview_silently_skips_blank_rows(session):
    """Trailing blank lines (Enter at end of file) and blank rows in the middle
    of the data shouldn't appear as 'name is required' errors."""
    e = _engagement(session)
    lines = _csv(
        "Main GL,Travelers,GL,GL-1,,,,",
        ",,,,,,,",  # fully blank row
        "WC,Hartford,WC,WC-1,,,,",
        "",  # trailing blank
        ",,,,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert [r.status for r in pre.rows] == ["new", "new"]
    assert pre.skipped_blank_rows == 3
    assert pre.error_count == 0


def test_preview_caps_at_max_rows(session, monkeypatch):
    """Pathological multi-row inputs must be rejected before the preview eats
    all available memory."""
    e = _engagement(session)
    # Cap to a tiny number for the test; production cap is MAX_ROWS=10_000.
    monkeypatch.setattr(policy_import, "MAX_ROWS", 3)
    lines = _csv(
        *[f"Policy {i},Travelers,GL,GL-{i},,,," for i in range(10)],
    )
    with pytest.raises(ImportFileError) as exc:
        policy_import.from_iterable(session, e, lines)
    assert "more than 3" in str(exc.value)


def test_missing_name_column_error_message_includes_actual_headers(session):
    """When the user's CSV lacks the 'name' column, the error should show
    what they did provide so they can spot the typo / wrong file fast."""
    e = _engagement(session)
    lines = ["Carrier,PolicyNumber", "Travelers,GL-1"]
    with pytest.raises(ImportFileError) as exc:
        policy_import.from_iterable(session, e, lines)
    assert "Carrier" in str(exc.value)
    assert "PolicyNumber" in str(exc.value)


def test_preview_uses_only_python_3_11_compatible_apis(session, tmp_path):
    """Regression: ``Path.read_text(newline=...)`` is 3.13+. Open the CSV in
    binary, decode manually, and confirm the preview path doesn't crash on
    APIs the project doesn't actually support yet."""
    import inspect

    src = inspect.getsource(policy_import)
    # Hard-rule: don't reach for the 3.13-only newline kwarg on read_text.
    # If a future change reintroduces it, this test will catch the slip
    # before it ships to a 3.11 user.
    assert "read_text(encoding=" in src or "read_text(" in src
    assert "read_text(newline=" not in src
    assert ", newline=" not in src or "open(" in src.split(", newline=")[0].splitlines()[-1]


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


# --- round-trip / id-update ---------------------------------------------


def _csv_with_id(*rows: str) -> list[str]:
    return [
        "id,name,carrier,coverage,policy_number,"
        "effective_date,expiration_date,location,description",
        *rows,
    ]


def test_preview_id_match_classifies_as_update(session):
    e = _engagement(session)
    p = policies.create(
        session,
        e,
        PolicyInput(name="Main GL", carrier="Travelers", policy_number="GL-9001"),
    )
    lines = _csv_with_id(
        f"{p.id},Main GL renewed,Travelers,GL,GL-9001,2027-01-01,2028-01-01,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.update_count == 1
    assert pre.new_count == 0
    assert pre.duplicate_count == 0
    row = pre.rows[0]
    assert row.status == "update"
    assert row.existing_id == p.id


def test_preview_id_not_in_engagement_is_error(session):
    e = _engagement(session)
    other = engagements.create(session, "Other")
    foreign = policies.create(
        session, other, PolicyInput(name="Foreign", carrier="X", policy_number="X-1")
    )
    lines = _csv_with_id(
        f"{foreign.id},Renamed,X,GL,X-1,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.error_count == 1
    assert "is not a policy in this engagement" in pre.rows[0].message


def test_preview_duplicate_id_in_csv_flagged(session):
    e = _engagement(session)
    p = policies.create(
        session,
        e,
        PolicyInput(name="Main GL", carrier="Travelers", policy_number="GL-9001"),
    )
    lines = _csv_with_id(
        f"{p.id},First edit,Travelers,GL,GL-9001,,,,",
        f"{p.id},Second edit,Travelers,GL,GL-9001,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.update_count == 1
    assert pre.error_count == 1
    assert "more than once" in pre.rows[1].message


def test_preview_id_skips_dedup_against_self(session):
    """Round-trip safety: re-importing an unchanged row with its own id
    must not be flagged as a duplicate of itself."""
    e = _engagement(session)
    p = policies.create(
        session,
        e,
        PolicyInput(name="Main GL", carrier="Travelers", policy_number="GL-9001"),
    )
    lines = _csv_with_id(
        f"{p.id},Main GL,Travelers,GL,GL-9001,,,,",
    )
    pre = policy_import.from_iterable(session, e, lines)
    assert [r.status for r in pre.rows] == ["update"]


def test_commit_applies_updates_in_place(session):
    e = _engagement(session)
    p = policies.create(
        session,
        e,
        PolicyInput(
            name="Main GL",
            carrier="Travelers",
            coverage="GL",
            policy_number="GL-9001",
            effective_date=date(2026, 1, 1),
            expiration_date=date(2027, 1, 1),
            location="HQ",
            description="primary",
        ),
    )
    original_id = p.id
    lines = _csv_with_id(
        f"{p.id},Main GL,Travelers,GL,GL-9001,2026-06-01,2027-06-01,Annex,renewed early",
    )
    pre = policy_import.from_iterable(session, e, lines)
    result = policy_import.commit(session, e, pre)
    assert result.imported == 0
    assert result.updated == 1
    refreshed = next(p for p in policies.list_for(session, e) if p.id == original_id)
    assert refreshed.effective_date == date(2026, 6, 1)
    assert refreshed.expiration_date == date(2027, 6, 1)
    assert refreshed.location == "Annex"
    assert refreshed.description == "renewed early"


def test_round_trip_export_then_import_no_op(session):
    """Export → re-import without edits should produce zero writes."""
    from openitems.domain import policy_export

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
    policies.create(
        session,
        e,
        PolicyInput(
            name="WC",
            carrier="Hartford",
            coverage="WC",
            policy_number="WC-1",
        ),
    )

    csv_text = policy_export.to_csv_text(policies.list_for(session, e))
    lines = csv_text.splitlines()
    pre = policy_import.from_iterable(session, e, lines)
    assert pre.update_count == 2
    assert pre.new_count == 0
    assert pre.error_count == 0

    result = policy_import.commit(session, e, pre)
    assert result.updated == 2
    assert result.imported == 0


def test_round_trip_with_edit(session):
    """Export, edit one cell, re-import → that one row is updated."""
    from openitems.domain import policy_export

    e = _engagement(session)
    p = policies.create(
        session,
        e,
        PolicyInput(name="Main GL", carrier="Travelers", policy_number="GL-9001"),
    )

    csv_text = policy_export.to_csv_text(policies.list_for(session, e))
    edited = csv_text.replace("Travelers", "Travelers Casualty")
    pre = policy_import.from_iterable(session, e, edited.splitlines())
    policy_import.commit(session, e, pre)

    refreshed = session.get(type(p), p.id)
    assert refreshed.carrier == "Travelers Casualty"
