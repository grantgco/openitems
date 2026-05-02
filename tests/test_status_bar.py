from __future__ import annotations

from openitems.tui.widgets.status_bar import StatusBar


def _plain(width: int) -> str:
    return StatusBar()._render_for_width(width).plain


def test_status_bar_always_includes_question_and_quit():
    """At every reasonable width, the discovery + escape hatches stay visible."""
    for w in (50, 60, 70, 80, 100, 120, 200):
        rendered = _plain(w)
        assert "? more" in rendered, f"missing `? more` at width {w}: {rendered!r}"
        assert "q quit" in rendered, f"missing `q quit` at width {w}: {rendered!r}"


def test_status_bar_always_includes_essential_head():
    """The 5 daily-essential keys (j/k, a, e, n, i) must survive any width."""
    for w in (50, 60, 80, 100, 200):
        rendered = _plain(w)
        for key in ("j/k", "a add", "e edit", "n note", "i jot"):
            assert key in rendered, f"missing {key!r} at width {w}: {rendered!r}"


def test_status_bar_drops_middle_entries_on_narrow_widths():
    """At 60 cols, middle entries (D digest, E switch, etc.) are dropped."""
    rendered = _plain(60)
    assert "D digest" not in rendered
    assert "E switch" not in rendered


def test_status_bar_shows_all_entries_on_wide_terminal():
    """At 200 cols everything fits."""
    rendered = _plain(200)
    for key in ("/ filter", "s advance", "f focus", "d del", "D digest", "E switch"):
        assert key in rendered, f"missing {key!r} on wide terminal: {rendered!r}"


def test_status_bar_never_exceeds_target_width():
    """The chosen subset must always fit within the target width."""
    sb = StatusBar()
    for w in (50, 60, 70, 80, 100, 120, 150, 200):
        text = sb._render_for_width(w)
        # Allowed to exceed only when the head+tail alone don't fit.
        if text.cell_len > w:
            # Verify the head+tail-only fallback fired.
            head_tail_only = sb._render_entries(
                StatusBar.ESSENTIAL_HEAD + StatusBar.ESSENTIAL_TAIL
            )
            assert text.cell_len == head_tail_only.cell_len
