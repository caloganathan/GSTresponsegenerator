"""
Persistence for conversations and matters.

Both record types are JSON documents in a directory, and both are written the
same way: to a temporary file in the destination directory, then moved into
place with `os.replace`. That move is atomic on POSIX and on Windows, so a
crash or a full disk mid-write leaves the previous version intact. There is no
half-written state a reader can observe.

This matters more for matters than for conversations. A matter record is the
working paper — the notice facts, the deliberation, the determination and the
verification trail — and a firm relying on it at peer review needs it to be
either the old version or the new one, never a truncated hybrid.

Corrupt files are skipped in listings and return None on read. A single bad
document must never take down the index.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config

DEFAULT_TITLE = "New Conversation"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Document IDs become filenames. Anything outside this alphabet — a slash, a
# "..", an encoded traversal — is a path, not an ID, and the user store
# (password hashes and live session tokens) sits one directory above the
# matters. The API's route pattern happens to block traversal today; that is
# a property of the web server's URL decoding, not of this module, and any
# future caller that takes an ID from a request body loses it. So it is
# enforced here, at the only place paths are built.
_DOCUMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _valid_id(name: Any) -> bool:
    return bool(_DOCUMENT_ID_RE.match(str(name or "")))


# ---------------------------------------------------------------------------
# Document primitives
#
# Conversations and matters differ only in which directory they live in and
# what shape they carry. Everything about getting them onto and off disk is
# shared, and is written once here.
# ---------------------------------------------------------------------------


def _write_document(directory: str, name: str, document: Dict[str, Any]) -> None:
    """Write one JSON document atomically, creating the directory if needed."""
    if not _valid_id(name):
        raise ValueError(f"Invalid document id: {name!r}")
    Path(directory).mkdir(parents=True, exist_ok=True)
    handle, staging_path = tempfile.mkstemp(
        dir=directory, prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(handle, "w") as staged:
            json.dump(document, staged, indent=2)
        os.replace(staging_path, os.path.join(directory, f"{name}.json"))
    except BaseException:
        # Never leave a stray .tmp- file behind, whatever went wrong.
        try:
            os.unlink(staging_path)
        except OSError:
            pass
        raise


def _read_document(directory: str, name: str,
                   label: str) -> Optional[Dict[str, Any]]:
    """Load one JSON document, or None if it is absent or unreadable."""
    if not _valid_id(name):
        return None
    path = os.path.join(directory, f"{name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as stored:
            return json.load(stored)
    except (json.JSONDecodeError, OSError) as problem:
        print(f"Could not read {label} {name}: {problem}")
        return None


def _remove_document(directory: str, name: str) -> bool:
    """Delete one document. True if it was there to delete."""
    if not _valid_id(name):
        return False
    path = os.path.join(directory, f"{name}.json")
    if not os.path.exists(path):
        return False
    os.unlink(path)
    return True


def _scan_documents(
    directory: str,
    summarise: Callable[[Dict[str, Any]], Dict[str, Any]],
    label: str,
) -> List[Dict[str, Any]]:
    """
    Read every document in a directory and reduce each to a summary.

    Anything that will not parse, or that is missing a field the summary needs,
    is reported and skipped — one damaged file must not empty the index.
    """
    Path(directory).mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, Any]] = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json") or filename.startswith("."):
            continue
        try:
            with open(os.path.join(directory, filename), "r") as stored:
                summaries.append(summarise(json.load(stored)))
        except (json.JSONDecodeError, KeyError, OSError, TypeError) as problem:
            print(f"Skipping unreadable {label} file {filename}: {problem}")

    summaries.sort(key=lambda entry: entry["created_at"], reverse=True)
    return summaries


# ---------------------------------------------------------------------------
# Conversations — the general council
# ---------------------------------------------------------------------------
#
# config.DATA_DIR is read at call time rather than bound at import, so tests
# can redirect storage with a monkeypatch. Keep it that way.


def ensure_conversation_dir() -> None:
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)


def conversation_file(conversation_id: str) -> str:
    if not _valid_id(conversation_id):
        raise ValueError(f"Invalid conversation id: {conversation_id!r}")
    return os.path.join(config.DATA_DIR, f"{conversation_id}.json")


# An exchange used to be stored under the names of the stages that produced
# it. It is now stored under what each part IS — the answers, the reviews of
# them, the ruling — and conversations written before the change are still on
# disk in the old shape. These tables are the whole of the difference: old key
# on the left, current key on the right, per level of the record.
#
# Only KEYS are translated. The labels a referee was shown ("Response A" in an
# old record, "Answer A" in a new one) are values, they appear inside the
# stored assessments as the referee wrote them, and the label-to-author map
# beside them is what gives them meaning. Rewriting one without the other
# would break the link, so a record keeps the labels it was written with.
_LEGACY_EXCHANGE_KEYS = {"stage1": "answers", "stage2": "reviews", "stage3": "ruling"}
_LEGACY_TEXT_KEY = {"response": "text"}
_LEGACY_REVIEW_KEYS = {"ranking": "assessment", "parsed_ranking": "order"}
_LEGACY_METADATA_KEYS = {"label_to_model": "authors",
                         "aggregate_rankings": "standings"}
_LEGACY_STANDING_KEYS = {"average_rank": "mean_position",
                         "rankings_count": "reviews_counted"}
_LEGACY_FAILURE_KEYS = {"stage1": "answers", "stage2": "reviews"}


def _rekey(record: Any, renames: Dict[str, str]) -> bool:
    """
    Move old keys to their current names, in place. True if anything moved.

    A record that already carries the current key keeps it: the old one is
    dropped rather than allowed to overwrite newer data.
    """
    if not isinstance(record, dict):
        return False
    moved = False
    for old, current in renames.items():
        if old in record:
            value = record.pop(old)
            record.setdefault(current, value)
            moved = True
    return moved


def upgrade_conversation(conversation: Dict[str, Any]) -> bool:
    """
    Bring a stored conversation up to the current shape, in place.

    Returns True if anything changed. Running it on a current record changes
    nothing, so it is safe on every read.
    """
    changed = False
    for message in conversation.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        changed |= _rekey(message, _LEGACY_EXCHANGE_KEYS)
        for answer in message.get("answers") or []:
            changed |= _rekey(answer, _LEGACY_TEXT_KEY)
        for review in message.get("reviews") or []:
            changed |= _rekey(review, _LEGACY_REVIEW_KEYS)
        changed |= _rekey(message.get("ruling"), _LEGACY_TEXT_KEY)

        metadata = message.get("metadata")
        changed |= _rekey(metadata, _LEGACY_METADATA_KEYS)
        if isinstance(metadata, dict):
            for standing in metadata.get("standings") or []:
                changed |= _rekey(standing, _LEGACY_STANDING_KEYS)
            changed |= _rekey(metadata.get("failures"), _LEGACY_FAILURE_KEYS)
    return changed


def write_conversation(conversation: Dict[str, Any]) -> None:
    _write_document(config.DATA_DIR, conversation["id"], conversation)


def read_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    One conversation, always in the current shape.

    A record written in the old shape is upgraded as it is read, so nothing
    above this function ever sees the old keys. The file itself is rewritten
    the next time the conversation is added to; `migrate_conversations` does
    them all at once.
    """
    conversation = _read_document(config.DATA_DIR, conversation_id, "conversation")
    if conversation is not None:
        upgrade_conversation(conversation)
    return conversation


def delete_conversation(conversation_id: str) -> bool:
    return _remove_document(config.DATA_DIR, conversation_id)


def open_conversation(conversation_id: str) -> Dict[str, Any]:
    """Create an empty conversation, store it and return it."""
    conversation = {
        "id": conversation_id,
        "created_at": _now(),
        "title": DEFAULT_TITLE,
        "messages": [],
    }
    write_conversation(conversation)
    return conversation


def conversation_index() -> List[Dict[str, Any]]:
    """Conversation summaries for the sidebar, newest first."""
    def summarise(document: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": document["id"],
            "created_at": document["created_at"],
            "title": document.get("title", DEFAULT_TITLE),
            "message_count": len(document["messages"]),
        }

    return _scan_documents(config.DATA_DIR, summarise, "conversation")


def _amend_conversation(
    conversation_id: str,
    change: Callable[[Dict[str, Any]], None],
) -> None:
    """
    Load a conversation, apply one change to it, and write it back.

    Every edit to a stored conversation goes through here, so each is a whole
    read-modify-write over the atomic writer and none can leave a half-applied
    record behind.
    """
    record = read_conversation(conversation_id)
    if record is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    change(record)
    write_conversation(record)


def _append_message(conversation_id: str, message: Dict[str, Any]) -> None:
    _amend_conversation(conversation_id,
                        lambda record: record["messages"].append(message))


def record_question(conversation_id: str, question: str) -> None:
    """Append what the user asked. Stored in chat-message form, as it is sent."""
    _append_message(conversation_id, {"role": "user", "content": question})


def record_exchange(
    conversation_id: str,
    answers: List[Dict[str, Any]],
    reviews: List[Dict[str, Any]],
    ruling: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append what the council made of the question.

    The metadata — who wrote which labelled answer, the standings, per-model
    failures and cost — is persisted alongside the answers, reviews and
    ruling, so a reloaded conversation renders exactly as it did live rather
    than losing its provenance.
    """
    _append_message(conversation_id, {
        "role": "assistant",
        "answers": answers,
        "reviews": reviews,
        "ruling": ruling,
        "metadata": metadata or {},
    })


def retitle_conversation(conversation_id: str, title: str) -> None:
    _amend_conversation(conversation_id,
                        lambda record: record.update(title=title))


def migrate_conversations(dry_run: bool = False) -> Dict[str, Any]:
    """
    Rewrite every stored conversation that is still in the old shape.

    The application does not need this — `read_conversation` upgrades on the
    way in — but anything else that opens the JSON directly does, and until a
    file is rewritten it is still in the shape only this module can read.
    Returns what was found; with `dry_run` nothing is written.

    Each rewrite is the same atomic replace as any other write, so an
    interrupted run leaves every file either wholly old or wholly current,
    and running it again finishes the job.
    """
    report: Dict[str, Any] = {"examined": 0, "upgraded": [], "current": 0,
                              "unreadable": [], "dry_run": dry_run}
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    for filename in sorted(os.listdir(config.DATA_DIR)):
        if not filename.endswith(".json") or filename.startswith("."):
            continue
        name = filename[:-len(".json")]
        report["examined"] += 1
        conversation = _read_document(config.DATA_DIR, name, "conversation")
        # A file whose id does not match its name is not one this module
        # wrote; leave it exactly as it is rather than write it somewhere new.
        if not isinstance(conversation, dict) or conversation.get("id") != name:
            report["unreadable"].append(name)
            continue
        if not upgrade_conversation(conversation):
            report["current"] += 1
            continue
        if not dry_run:
            write_conversation(conversation)
        report["upgraded"].append(name)
    return report


# ---------------------------------------------------------------------------
# Matters — the compliance panel
#
# A matter is the unit of work for the panel: the notice facts, the full
# deliberation, the determination, and the verification result. Persisting the
# whole deliberation is not an implementation detail — that record IS the
# working paper the firm relies on at peer review.
# ---------------------------------------------------------------------------


def _matters_dir() -> str:
    return os.path.join(config.STATE_DIR, "matters")


def _matter_path(matter_id: str) -> str:
    return os.path.join(_matters_dir(), f"{matter_id}.json")


def save_matter(matter: Dict[str, Any]) -> None:
    _write_document(_matters_dir(), matter["id"], matter)


def get_matter(matter_id: str) -> Optional[Dict[str, Any]]:
    return _read_document(_matters_dir(), matter_id, "matter")


def delete_matter(matter_id: str) -> bool:
    return _remove_document(_matters_dir(), matter_id)


def create_matter(matter_id: str, intake: Dict[str, Any], domain: str,
                  tier: str, created_by: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create a matter record from the intake form."""
    opened_at = _now()
    matter = {
        "id": matter_id,
        "created_at": opened_at,
        "updated_at": opened_at,
        "domain": domain,
        "tier": tier,
        "status": "draft",
        "intake": intake,
        "result": None,
        "metadata": {},
        "created_by": {
            "id": (created_by or {}).get("id"),
            "name": (created_by or {}).get("name"),
            "email": (created_by or {}).get("email"),
        } if created_by else None,
    }
    save_matter(matter)
    return matter


def complete_matter(matter_id: str, result: Dict[str, Any],
                    metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attach the panel output to a matter and mark it complete."""
    matter = get_matter(matter_id)
    if matter is None:
        return None
    matter["result"] = result
    matter["metadata"] = metadata
    matter["status"] = "complete"
    matter["updated_at"] = _now()
    save_matter(matter)
    return matter


def list_matters() -> List[Dict[str, Any]]:
    """Matter summaries for the dashboard, newest first."""
    def summarise(document: Dict[str, Any]) -> Dict[str, Any]:
        intake = document.get("intake", {})
        outcome = document.get("result") or {}
        determination = outcome.get("determination") or {}
        verification = outcome.get("verification") or {}
        limbs = intake.get("defects") or []
        # Cost scales with the limbs that convened counsel, not with the limb
        # count, so the estimator needs both to learn from this matter.
        panel_limbs = [d for d in limbs
                       if (d.get("posture") or "undecided")
                       in ("contested", "partial", "undecided")]
        return {
            "id": document["id"],
            "defect_count": len(limbs),
            "panel_defect_count": len(panel_limbs),
            "created_at": document["created_at"],
            "updated_at": document.get("updated_at", document["created_at"]),
            "domain": document.get("domain", "gst"),
            "tier": document.get("tier"),
            "status": document.get("status", "draft"),
            "client_name": intake.get("client_name", ""),
            "notice_type": intake.get("notice_type", ""),
            "state": intake.get("state", ""),
            "tax_period": intake.get("tax_period", ""),
            "amount_disputed": intake.get("amount_disputed"),
            "due_date": intake.get("due_date"),
            "confidence": determination.get("confidence"),
            "risk_flag_count": len(determination.get("risk_flags") or []),
            "verification_summary": verification.get("summary"),
            "usage": (document.get("metadata") or {}).get("usage"),
            "created_by": document.get("created_by"),
        }

    return _scan_documents(_matters_dir(), summarise, "matter")
