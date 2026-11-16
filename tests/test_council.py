"""Tests for reading a referee's order of merit, the standings, and history building."""

from backend.council import (
    build_history_messages,
    format_history_snippet,
    read_order_of_merit,
    tally_standings,
)


class TestReadOrderOfMerit:
    def test_strict_format(self):
        text = """Answer A is decent. Answer B is stronger.

ORDER OF MERIT:
1. Answer B
2. Answer A
3. Answer C"""
        assert read_order_of_merit(text) == [
            "Answer B", "Answer A", "Answer C"
        ]

    def test_duplicates_deduped(self):
        text = """ORDER OF MERIT:
1. Answer B
2. Answer B
3. Answer A"""
        assert read_order_of_merit(text) == ["Answer B", "Answer A"]

    def test_invalid_labels_dropped(self):
        text = """ORDER OF MERIT:
1. Answer D
2. Answer A
3. Answer B"""
        valid = ["Answer A", "Answer B", "Answer C"]
        assert read_order_of_merit(text, valid) == ["Answer A", "Answer B"]

    def test_prose_mentions_after_header_ignored_when_numbered(self):
        text = """As I noted, Answer C was weak.

ORDER OF MERIT:
1. Answer A
2. Answer B
3. Answer C

Overall Answer C had issues but Answer A shined."""
        # Numbered-list matches take priority; trailing prose "Answer C"/"A"
        # mentions are unnumbered and deduped away.
        assert read_order_of_merit(text) == [
            "Answer A", "Answer B", "Answer C"
        ]

    def test_fallback_without_header(self):
        text = "Best is Answer B, then Answer A, finally Answer C."
        assert read_order_of_merit(text) == [
            "Answer B", "Answer A", "Answer C"
        ]

    def test_last_header_occurrence_wins(self):
        text = """I will give my ORDER OF MERIT: below after analysis.
Answer A is good. Answer B is bad.

ORDER OF MERIT:
1. Answer A
2. Answer B"""
        assert read_order_of_merit(text) == ["Answer A", "Answer B"]

    def test_empty(self):
        assert read_order_of_merit("no labels here") == []


class TestRefereeHeaderTolerance:
    """
    The prompt asks for ORDER OF MERIT, but a model that has read enough of the
    internet will sometimes answer in a format it was never asked for. Losing a
    whole review to a header mismatch is not an acceptable failure mode.
    """

    def test_legacy_header_still_parses(self):
        text = """FINAL RANKING:
1. Answer C
2. Answer A"""
        assert read_order_of_merit(text) == ["Answer C", "Answer A"]

    def test_bare_ranking_header_parses(self):
        text = """RANKING:
1. Answer A
2. Answer B"""
        assert read_order_of_merit(text) == ["Answer A", "Answer B"]

    def test_latest_header_of_any_kind_wins(self):
        # A model that restates one header in prose and closes with another.
        text = """My RANKING: will follow. Answer B disappointed.

ORDER OF MERIT:
1. Answer A
2. Answer B"""
        assert read_order_of_merit(text) == ["Answer A", "Answer B"]


class TestStandings:
    LABELS = {
        "Answer A": "model-a",
        "Answer B": "model-b",
        "Answer C": "model-c",
    }

    def test_normalized_scores(self):
        reviews = [
            # Reviewer ranked B best, C worst (own response A excluded)
            {"order": ["Answer B", "Answer C"]},
            # Reviewer ranked A best, C worst (own response B excluded)
            {"order": ["Answer A", "Answer C"]},
        ]
        agg = tally_standings(reviews, self.LABELS)
        by_model = {a["model"]: a for a in agg}
        assert by_model["model-a"]["score"] == 0.0
        assert by_model["model-b"]["score"] == 0.0
        assert by_model["model-c"]["score"] == 1.0
        assert by_model["model-c"]["reviews_counted"] == 2
        # Sorted best (lowest score) first
        assert agg[-1]["model"] == "model-c"

    def test_empty_orders_skipped(self):
        reviews = [{"order": []}, {"order": ["Answer A"]}]
        agg = tally_standings(reviews, self.LABELS)
        assert len(agg) == 1
        assert agg[0]["model"] == "model-a"
        assert agg[0]["score"] == 0.5  # an order of one says nothing

    def test_unknown_labels_ignored(self):
        reviews = [{"order": ["Answer Z", "Answer A"]}]
        agg = tally_standings(reviews, self.LABELS)
        assert [a["model"] for a in agg] == ["model-a"]


class TestHistory:
    MESSAGES = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "answers": [], "reviews": [],
         "ruling": {"model": "m", "text": "first answer"}},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "answers": [], "reviews": [],
         "ruling": {"model": "m", "text": "second answer"}},
    ]

    def test_builds_pairs(self):
        history = build_history_messages(self.MESSAGES)
        assert history == [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "second answer"},
        ]

    def test_caps_turns(self):
        history = build_history_messages(self.MESSAGES, max_turns=1)
        assert history == [
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "second answer"},
        ]

    def test_skips_failed_assistant_messages(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "ruling": {}},  # the chair recorded nothing
        ]
        assert build_history_messages(messages) == [
            {"role": "user", "content": "q"}
        ]

    def test_snippet_truncation(self):
        history = [{"role": "user", "content": "x" * 5000}]
        snippet = format_history_snippet(history, max_chars=100)
        assert "[...truncated]" in snippet
        assert len(snippet) < 200

    def test_snippet_empty(self):
        assert format_history_snippet([]) == ""
