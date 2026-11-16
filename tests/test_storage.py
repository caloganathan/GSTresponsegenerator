"""Tests for conversation storage."""

import json
import os

import pytest

from backend import config, storage


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    return tmp_path


def test_create_and_get():
    conv = storage.open_conversation("abc")
    assert conv["id"] == "abc"
    loaded = storage.read_conversation("abc")
    assert loaded["title"] == "New Conversation"
    assert loaded["messages"] == []


def test_add_messages_and_metadata_persisted():
    storage.open_conversation("abc")
    storage.record_question("abc", "hello")
    storage.record_exchange(
        "abc",
        answers=[{"model": "m1", "text": "r1"}],
        reviews=[],
        ruling={"model": "m1", "text": "final"},
        metadata={"usage": {"total_cost": 0.5}},
    )
    loaded = storage.read_conversation("abc")
    assert len(loaded["messages"]) == 2
    assistant = loaded["messages"][1]
    assert assistant["metadata"]["usage"]["total_cost"] == 0.5
    assert assistant["ruling"]["text"] == "final"


def test_delete():
    storage.open_conversation("abc")
    assert storage.delete_conversation("abc") is True
    assert storage.read_conversation("abc") is None
    assert storage.delete_conversation("abc") is False


def test_corrupt_file_skipped_in_listing(temp_data_dir):
    storage.open_conversation("good")
    (temp_data_dir / "bad.json").write_text("{not json")
    listing = storage.conversation_index()
    assert [c["id"] for c in listing] == ["good"]


def test_corrupt_file_returns_none():
    path = storage.conversation_file("bad")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not json")
    assert storage.read_conversation("bad") is None


def test_no_temp_files_left_behind(temp_data_dir):
    storage.open_conversation("abc")
    leftovers = [f for f in os.listdir(temp_data_dir) if f.startswith(".tmp-")]
    assert leftovers == []


def test_listing_sorted_newest_first(temp_data_dir):
    for cid, ts in [("one", "2026-01-01T00:00:00"), ("two", "2026-06-01T00:00:00")]:
        storage.write_conversation({
            "id": cid, "created_at": ts, "title": cid, "messages": []
        })
    listing = storage.conversation_index()
    assert [c["id"] for c in listing] == ["two", "one"]


class TestDocumentIdValidation:
    """
    IDs become filenames, and the matters directory sits one level below the
    user store (password hashes and live session tokens). An ID that is really
    a path — "../users", an absolute path, an encoded traversal — must never
    reach os.path.join. The API route pattern blocks this for URL callers
    today, but that is the web server's property, not this module's, and the
    guard belongs where the path is built.
    """

    BAD_IDS = ["../users", "../../etc/passwd", "a/b", "matters/../users",
               "", ".", "..", "with space", "id.json", "a" * 65, "sub/dir/x"]
    GOOD_IDS = ["abc", "a1b2c3d4-1111-2222-3333-444455556666",
                "matter_01", "MATTER-01", "a" * 64]

    def test_get_matter_rejects_a_traversal_id(self, temp_data_dir):
        for bad in self.BAD_IDS:
            assert storage.get_matter(bad) is None, bad

    def test_delete_matter_rejects_a_traversal_id(self, temp_data_dir):
        for bad in self.BAD_IDS:
            assert storage.delete_matter(bad) is False, bad

    def test_save_matter_rejects_a_traversal_id(self, temp_data_dir):
        for bad in self.BAD_IDS:
            with pytest.raises(ValueError):
                storage.save_matter({"id": bad})

    def test_a_traversal_delete_cannot_reach_a_sibling_file(self, tmp_path,
                                                            monkeypatch):
        """The concrete attack: delete_matter('../users') must not remove the
        user store."""
        monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
        users_file = tmp_path / "users.json"
        users_file.write_text('{"users": [], "sessions": {}}')
        assert storage.delete_matter("../users") is False
        assert users_file.exists()

    def test_valid_ids_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
        for good in self.GOOD_IDS:
            storage.save_matter({"id": good, "status": "draft"})
            assert storage.get_matter(good)["id"] == good
            assert storage.delete_matter(good) is True


class TestConversationsWrittenBeforeTheRename:
    """
    An exchange used to be stored under the names of the stages that produced
    it — `stage1`, `stage2`, `stage3` — and is now stored as `answers`,
    `reviews` and `ruling`. Conversations already on disk were not rewritten
    by the change, so every one of them is in the old shape until something
    touches it. A reader that only knows the new keys renders those as empty
    exchanges, silently: the thread opens, the questions are there, and every
    answer the council ever gave is missing.
    """

    @staticmethod
    def _old_record(conversation_id="old"):
        return {
            "id": conversation_id,
            "created_at": "2026-03-01T10:00:00+00:00",
            "title": "An old thread",
            "messages": [
                {"role": "user", "content": "what is the rate?"},
                {
                    "role": "assistant",
                    "stage1": [
                        {"model": "m/a", "response": "eighteen", "usage": {"cost": 0.1}},
                        {"model": "m/b", "response": "twenty-four"},
                    ],
                    "stage2": [{
                        "model": "m/a",
                        "ranking": "Response B overstates it.\nFINAL RANKING:\n1. Response A\n2. Response B",
                        "parsed_ranking": ["Response A", "Response B"],
                        "own_label": None,
                        "parse_complete": True,
                    }],
                    "stage3": {"model": "m/chair", "response": "Eighteen per cent."},
                    "metadata": {
                        "label_to_model": {"Response A": "m/a", "Response B": "m/b"},
                        "aggregate_rankings": [
                            {"model": "m/a", "score": 0.0,
                             "average_rank": 1.0, "rankings_count": 1},
                        ],
                        "failures": {"stage1": [{"model": "m/c", "error": "boom"}],
                                     "stage2": []},
                        "usage": {"total_cost": 0.4},
                        "mode": "full",
                    },
                },
            ],
        }

    def _write_old(self, tmp_path, conversation_id="old"):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / f"{conversation_id}.json").write_text(
            json.dumps(self._old_record(conversation_id)))

    def test_an_old_record_reads_in_the_current_shape(self, temp_data_dir):
        self._write_old(temp_data_dir)
        exchange = storage.read_conversation("old")["messages"][1]

        assert [a["text"] for a in exchange["answers"]] == ["eighteen", "twenty-four"]
        assert exchange["answers"][0]["usage"] == {"cost": 0.1}
        assert exchange["ruling"] == {"model": "m/chair", "text": "Eighteen per cent."}
        review = exchange["reviews"][0]
        assert review["order"] == ["Response A", "Response B"]
        assert review["assessment"].startswith("Response B overstates it.")
        assert review["parse_complete"] is True
        metadata = exchange["metadata"]
        assert metadata["authors"] == {"Response A": "m/a", "Response B": "m/b"}
        assert metadata["standings"] == [
            {"model": "m/a", "score": 0.0, "mean_position": 1.0, "reviews_counted": 1}]
        assert metadata["failures"] == {
            "answers": [{"model": "m/c", "error": "boom"}], "reviews": []}
        assert metadata["usage"] == {"total_cost": 0.4}

    def test_no_old_key_survives_anywhere_in_the_record(self, temp_data_dir):
        self._write_old(temp_data_dir)
        flat = json.dumps(storage.read_conversation("old"))
        for old in ('"stage1"', '"stage2"', '"stage3"', '"response"', '"ranking"',
                    '"parsed_ranking"', '"label_to_model"', '"aggregate_rankings"',
                    '"average_rank"', '"rankings_count"'):
            assert old not in flat, old

    def test_the_labels_a_record_was_written_with_are_left_alone(self, temp_data_dir):
        """
        The referee's own words say "Response B". The map beside them is what
        says who Response B was. Relabelling one and not the other would cut
        every stored assessment loose from the answer it was about.
        """
        self._write_old(temp_data_dir)
        exchange = storage.read_conversation("old")["messages"][1]
        for label in exchange["reviews"][0]["order"]:
            assert label in exchange["metadata"]["authors"]
            assert label in exchange["reviews"][0]["assessment"]

    def test_the_old_ruling_still_feeds_the_next_question(self, temp_data_dir):
        """History is built from the ruling; an unread one drops the context."""
        from backend.council import build_history_messages
        self._write_old(temp_data_dir)
        history = build_history_messages(storage.read_conversation("old")["messages"])
        assert history == [
            {"role": "user", "content": "what is the rate?"},
            {"role": "assistant", "content": "Eighteen per cent."},
        ]

    def test_adding_to_an_old_conversation_rewrites_it_current(self, temp_data_dir):
        self._write_old(temp_data_dir)
        storage.record_question("old", "and from when?")
        on_disk = json.loads((temp_data_dir / "old.json").read_text())
        assert "stage1" not in on_disk["messages"][1]
        assert on_disk["messages"][1]["ruling"]["text"] == "Eighteen per cent."
        assert on_disk["messages"][2] == {"role": "user", "content": "and from when?"}

    def test_reading_alone_does_not_touch_the_file(self, temp_data_dir):
        self._write_old(temp_data_dir)
        before = (temp_data_dir / "old.json").read_text()
        storage.read_conversation("old")
        storage.conversation_index()
        assert (temp_data_dir / "old.json").read_text() == before

    def test_upgrading_twice_changes_nothing_the_second_time(self):
        record = self._old_record()
        assert storage.upgrade_conversation(record) is True
        import copy
        once = copy.deepcopy(record)
        assert storage.upgrade_conversation(record) is False
        assert record == once

    def test_a_current_key_is_never_overwritten_by_an_old_one(self):
        record = {"messages": [{
            "role": "assistant",
            "ruling": {"model": "m", "text": "the newer ruling"},
            "stage3": {"model": "m", "response": "a stale copy"},
        }]}
        storage.upgrade_conversation(record)
        assert record["messages"][0]["ruling"]["text"] == "the newer ruling"
        assert "stage3" not in record["messages"][0]

    def test_migrate_rewrites_old_files_and_leaves_current_ones(self, temp_data_dir):
        self._write_old(temp_data_dir, "old-one")
        self._write_old(temp_data_dir, "old-two")
        storage.open_conversation("fresh")
        fresh_before = (temp_data_dir / "fresh.json").read_text()

        report = storage.migrate_conversations()
        assert report["examined"] == 3
        assert report["upgraded"] == ["old-one", "old-two"]
        assert report["current"] == 1
        assert report["unreadable"] == []
        assert (temp_data_dir / "fresh.json").read_text() == fresh_before
        on_disk = json.loads((temp_data_dir / "old-one.json").read_text())
        assert on_disk["messages"][1]["answers"][0]["text"] == "eighteen"

        again = storage.migrate_conversations()
        assert again["upgraded"] == [] and again["current"] == 3

    def test_a_dry_run_reports_and_writes_nothing(self, temp_data_dir):
        self._write_old(temp_data_dir)
        before = (temp_data_dir / "old.json").read_text()
        report = storage.migrate_conversations(dry_run=True)
        assert report["upgraded"] == ["old"] and report["dry_run"] is True
        assert (temp_data_dir / "old.json").read_text() == before

    def test_a_damaged_file_is_reported_and_left_exactly_as_it_was(self, temp_data_dir):
        (temp_data_dir / "broken.json").write_text("{not json")
        (temp_data_dir / "stray.json").write_text('{"id": "someone-else", "messages": []}')
        self._write_old(temp_data_dir)
        report = storage.migrate_conversations()
        assert report["unreadable"] == ["broken", "stray"]
        assert report["upgraded"] == ["old"]
        assert (temp_data_dir / "broken.json").read_text() == "{not json"
        assert (temp_data_dir / "stray.json").read_text() == \
            '{"id": "someone-else", "messages": []}'
