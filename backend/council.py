"""
The general council: every seat answers, the seats referee one another with
authorship withheld, and a chair settles it.

This is the heritage mode. The compliance panel in `panel.py` is a different
deliberation — its counsel answer different questions, so nothing there is
ranked — and shares only the transport underneath.
"""

import asyncio
import re
from collections import defaultdict
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from .config import CHAIRMAN_MODEL, COUNCIL_MODELS, HISTORY_MAX_TURNS, TITLE_MODEL
from .openrouter import ask_model, ask_models

# Headers that mark the start of a referee's closing ordered list. The first is
# what the prompt asks for; the rest are formats models fall into unprompted and
# which are cheaper to accept than to argue with.
RANKING_HEADERS = (
    "ORDER OF MERIT:",
    "FINAL RANKING:",
    "RANKING:",
)

# A conversation title is a sidebar label, so it is held to one short line.
# Anything longer is cut and closed with an ellipsis that counts toward the
# limit.
TITLE_FALLBACK = "New Conversation"
TITLE_MAX_CHARS = 50
TITLE_ELLIPSIS = "..."


def build_history_messages(
    prior_messages: List[Dict[str, Any]],
    max_turns: int = HISTORY_MAX_TURNS,
) -> List[Dict[str, str]]:
    """
    Convert stored conversation messages into chat messages usable as context.

    User messages pass through; assistant messages are represented by their
    ruling — the answer the chair gave. Only the most recent `max_turns` exchanges are kept
    to bound token usage.
    """
    history: List[Dict[str, str]] = []
    for msg in prior_messages:
        if msg.get("role") == "user" and msg.get("content"):
            history.append({"role": "user", "content": msg["content"]})
        elif msg.get("role") == "assistant":
            final = (msg.get("ruling") or {}).get("text")
            if final:
                history.append({"role": "assistant", "content": final})
    # Keep the last N user/assistant pairs
    return history[-(max_turns * 2):]


def format_history_snippet(
    history: List[Dict[str, str]],
    max_turns: int = 3,
    max_chars: int = 1500,
) -> str:
    """Compact text rendering of recent history for inclusion inside prompts."""
    recent = history[-(max_turns * 2):]
    if not recent:
        return ""
    lines = []
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Council answer"
        content = msg["content"]
        if len(content) > max_chars:
            content = content[:max_chars] + " [...truncated]"
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


async def collect_answers(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    web_search: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Opening: put the question to every seat on the council at once.

    Returns the answers that came back and the seats that failed. An answer
    carries 'model', 'text' and 'usage'; a failure carries 'model' and 'error'.
    """
    messages = list(history or []) + [{"role": "user", "content": question}]

    responses = await ask_models(
        COUNCIL_MODELS, messages, web_search=web_search
    )

    answered = [
        {"model": seat, "text": reply["content"], "usage": reply.get("usage")}
        for seat, reply in responses.items() if reply.get("ok")
    ]
    failures = [
        {"model": seat, "error": reply.get("error", "unknown")}
        for seat, reply in responses.items() if not reply.get("ok")
    ]
    return answered, failures


def _referee_prompt(
    question: str,
    labelled_answers: List[Tuple[str, str]],
    history_snippet: str,
) -> str:
    answers_block = "\n\n".join(
        f"Answer {label}:\n{text}" for label, text in labelled_answers
    )
    context_block = (
        f"For context, here is the recent conversation that led to this "
        f"question:\n\n{history_snippet}\n\n"
        if history_snippet else ""
    )
    labels_list = ", ".join(f"Answer {label}" for label, _ in labelled_answers)

    return f"""Act as an impartial referee. Several answers to one question are
set out below. Their authors are withheld from you deliberately, and one of the
answers may be missing because it was your own — judge only what you are shown.

{context_block}The question put to the council:

{question}

The answers under review:

{answers_block}

Work through this in two parts.

PART ONE — assess each answer on its own terms. Take them one at a time and say,
for each: whether its factual claims hold up, whether it engaged the actual
question or drifted to an adjacent one, where its reasoning is load-bearing and
where it is decorative, and what it omitted that a careful reader would want.
Name any claim you believe is wrong or unsupported, and say why. Do not soften a
real objection to seem even-handed, and do not manufacture criticism of an answer
that is simply good.

PART TWO — order the answers you were shown, strongest first. Rank on how well
each one serves someone who has to act on it, not on length or polish. If two are
genuinely close, break the tie on accuracy before style. If the best answer still
has a defect, rank it first and say so in Part One rather than demoting it.

Close your reply with the ordering on its own lines, in exactly this shape:

ORDER OF MERIT:
1. Answer B
2. Answer A

Rules for that closing block: the header on its own line in capitals, one label
per numbered line and nothing else on the line, every label you were shown
appearing once and once only, no commentary inside the block. The labels
available to you are: {labels_list}.

Begin with Part One."""


async def collect_reviews(
    question: str,
    answers: List[Dict[str, Any]],
    history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[Dict[str, str]]]:
    """
    Review: every seat referees the others, with authorship withheld.

    A seat is never shown its own answer, so it cannot place itself first —
    which is what removes self-preference from the standings.

    Returns the reviews, the label-to-author mapping, and the seats that
    failed to review.
    """
    # One capital letter per answer, in the order the answers came back.
    labels = [chr(ord("A") + seat) for seat in range(len(answers))]

    authors = {
        f"Answer {label}": result["model"]
        for label, result in zip(labels, answers)
    }
    label_of = {v: k for k, v in authors.items()}

    history_snippet = format_history_snippet(history or [])

    # Build one prompt per ranker, excluding its own response.
    # Tuples: (ranker model, its own label if any, labels it will see, prompt)
    ranker_prompts: List[Tuple[str, Optional[str], List[str], str]] = []
    for ranker in COUNCIL_MODELS:
        own_label = label_of.get(ranker)
        shown = [
            (label, result["text"])
            for label, result in zip(labels, answers)
            if f"Answer {label}" != own_label
        ]
        if len(shown) < 2:
            continue  # one answer cannot be put in order
        valid_labels = [f"Answer {label}" for label, _ in shown]
        prompt = _referee_prompt(question, shown, history_snippet)
        ranker_prompts.append((ranker, own_label, valid_labels, prompt))

    tasks = [
        ask_model(ranker, [{"role": "user", "content": prompt}])
        for ranker, _, _, prompt in ranker_prompts
    ]
    responses = await asyncio.gather(*tasks) if tasks else []

    reviews: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for (ranker, own_label, valid_labels, _), response in zip(ranker_prompts, responses):
        if not response.get("ok"):
            failures.append({"model": ranker, "error": response.get("error", "unknown")})
            continue
        verdict = response["content"]
        ordering = read_order_of_merit(verdict, valid_labels)
        reviews.append({
            "model": ranker,
            "assessment": verdict,
            "order": ordering,
            "own_label": own_label,
            "parse_complete": len(ordering) == len(valid_labels),
            "usage": response.get("usage"),
        })

    return reviews, authors, failures


async def chair_ruling(
    question: str,
    answers: List[Dict[str, Any]],
    reviews: List[Dict[str, Any]],
    authors: Optional[Dict[str, str]] = None,
    standings: Optional[List[Dict[str, Any]]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Ruling: the chair settles the council and writes the answer.

    The chair is given the answers, the referees' assessments, which label
    belonged to which seat (so a verdict on "Answer B" can be tied to the
    answer it was about), and the standings worked out from the reviews.
    """
    label_of = {v: k for k, v in (authors or {}).items()}

    answers_text = "\n\n".join(
        f"[{label_of.get(answer['model'], 'unlabeled')}] "
        f"Answer from {answer['model']}:\n{answer['text']}"
        for answer in answers
    )

    review_section = ""
    if reviews:
        mapping_text = "\n".join(
            f"- {label} = {model}" for label, model in (authors or {}).items()
        )
        reviews_text = "\n\n".join(
            f"Reviewer: {result['model']}\nEvaluation:\n{result['assessment']}"
            for result in reviews
        )
        aggregate_text = "\n".join(
            f"{i + 1}. {agg['model']} (normalized score {agg['score']}, "
            f"{agg['reviews_counted']} peer reviews)"
            for i, agg in enumerate(standings or [])
        ) or "No standings could be worked out from the reviews."

        review_section = f"""
WHAT THE REFEREES SAID
Each referee saw the others' answers without authorship, and never its own:

{reviews_text}

Which label belonged to which model:
{mapping_text}

Where the referees landed overall, strongest first — a lower score is better:
{aggregate_text}
"""

    context_block = ""
    history_snippet = format_history_snippet(history or [], max_turns=HISTORY_MAX_TURNS)
    if history_snippet:
        context_block = f"""
WHAT CAME BEFORE
The question below continues this exchange:
{history_snippet}
"""

    reviewed_clause = (
        " They then reviewed one another's work without knowing who wrote what."
        if reviews else ""
    )

    chairman_prompt = f"""You are chairing a council. Several models were asked
the same question and answered independently.{reviewed_clause} Their work is
below. Yours is to settle it.
{context_block}
THE QUESTION

{question}

WHAT THE COUNCIL ANSWERED
{answers_text}
{review_section}
Now write the answer the user should receive. How to weigh what you have:

Treat the referees as informed opinion, not as instruction. Where they are
right, follow them. Where the answer they placed first carries a mistake one of
them caught, take the answer and drop the mistake — you are not bound by the
order.

Where the council genuinely split on a question of substance, do not average
the positions into something no member argued. Decide, say which way you went,
and give the reason in a line.

Keep what is specific. A concrete figure, a named exception, a worked step —
these are the reason one answer beat another, and they are the first things
lost to a cautious summary. Do not trade them for safer phrasing.

Where real doubt survives — the council divided and nothing available settles
it — say so plainly and say what would settle it. A confident answer built over
an unresolved disagreement is the worst thing you can hand back.

Write to the user directly. They asked a question; they did not ask about the
council, the referees, or how this answer was assembled. None of that belongs
in your reply.

Your answer:"""

    ruling = await ask_model(
        CHAIRMAN_MODEL,
        list(history or []) + [{"role": "user", "content": chairman_prompt}],
    )
    if ruling.get("ok"):
        return {"model": CHAIRMAN_MODEL, "text": ruling["content"],
                "usage": ruling.get("usage")}

    # The chair failing must not take the council's work with it: the answers
    # and reviews already collected stay on screen beside this message.
    return {
        "model": CHAIRMAN_MODEL,
        "text": f"The chair could not write a ruling "
                f"({ruling.get('error', 'unknown error')}). "
                f"The council's individual answers were collected and are kept "
                f"with this conversation.",
        "error": True,
    }


def read_order_of_merit(
    reply: str,
    valid_labels: Optional[List[str]] = None,
) -> List[str]:
    """
    Pull the closing ordered list out of a referee's reply.

    Deduplicates labels (first occurrence wins) and, when valid_labels is
    given, drops any label that wasn't actually in the ranked set — so stray
    "Answer X" mentions in prose can't corrupt the order.
    """
    section = reply
    # Take the LAST header present: models restate the header in prose more
    # often than they emit two genuine blocks, and the real one closes the
    # reply. RANKING_HEADERS carries the legacy wording because a model that
    # has seen enough of the internet will sometimes answer in it regardless
    # of what it was asked for.
    cut = max(
        (reply.rfind(header) + len(header) for header in RANKING_HEADERS
         if header in reply),
        default=-1,
    )
    if cut >= 0:
        section = reply[cut:]

    # Prefer the strict numbered-list format
    matches = re.findall(r"\d+\.\s*(Answer [A-Z])", section)
    if not matches:
        # Failing that, every "Answer X" mentioned, in the order mentioned
        matches = re.findall(r"Answer [A-Z]", section)

    valid = set(valid_labels) if valid_labels is not None else None
    seen = set()
    ordered = []
    for label in matches:
        if label in seen:
            continue
        if valid is not None and label not in valid:
            continue
        seen.add(label)
        ordered.append(label)
    return ordered


def tally_standings(
    reviews: List[Dict[str, Any]],
    authors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Turn the referees' separate orderings into one set of standings.

    Each referee orders a different subset, because its own answer is
    withheld from it, so raw positions cannot be compared across reviews.
    Each position is therefore scaled to [0, 1] within its own review
    (0 placed first, 1 placed last) and the scaled positions are averaged.
    """
    scores = defaultdict(list)
    positions = defaultdict(list)

    for entry in reviews:
        parsed = entry.get("order") or []
        n = len(parsed)
        if n == 0:
            continue
        for pos, label in enumerate(parsed, start=1):
            model = authors.get(label)
            if model is None:
                continue
            positions[model].append(pos)
            scores[model].append((pos - 1) / (n - 1) if n > 1 else 0.5)

    standings = [
        {
            "model": model,
            "score": round(sum(model_scores) / len(model_scores), 3),
            "mean_position": round(sum(positions[model]) / len(positions[model]), 2),
            "reviews_counted": len(model_scores),
        }
        for model, model_scores in scores.items()
    ]
    # sorted() is stable, as list.sort() was: tied seats keep first-seen order.
    return sorted(standings, key=lambda seat: seat["score"])


def _sum_usage(*usage_lists: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate token counts and cost across stages (missing values ignored)."""
    total_tokens = 0
    total_cost = 0.0
    for usages in usage_lists:
        for usage in usages:
            if not usage:
                continue
            total_tokens += usage.get("total_tokens") or 0
            total_cost += usage.get("cost") or 0.0
    return {"total_tokens": total_tokens, "total_cost": round(total_cost, 6)}


async def title_for_conversation(question: str) -> str:
    """Name a conversation after its opening question, for the sidebar."""
    naming_request = (
        "Give this conversation a name for a sidebar list: three to five words "
        "that say what the question below is about.\n"
        "Reply with the name alone, on one line, with no quotation marks and no "
        "closing punctuation.\n\n"
        f"The question:\n{question}\n\n"
        "The name:"
    )
    response = await ask_model(
        TITLE_MODEL,
        [{"role": "user", "content": naming_request}],
        timeout=30.0,
        effort="none",
    )
    if not response.get("ok"):
        return TITLE_FALLBACK

    title = response.get("content", TITLE_FALLBACK).strip().strip("\"'")
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS - len(TITLE_ELLIPSIS)] + TITLE_ELLIPSIS
    return title or TITLE_FALLBACK


async def run_council_stream(
    question: str,
    prior_messages: Optional[List[Dict[str, Any]]] = None,
    mode: str = "full",
    web_search: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Run one deliberation, yielding an event as each part of it lands.

    Modes:
        "full": answers → blind review → ruling
        "quick": answers → ruling (no review)

    Events: answers_start, answers_complete, reviews_start, reviews_complete,
    ruling_start, ruling_complete, summary. The summary event carries the
    complete metadata (authors, standings, failures, usage).
    """
    history = build_history_messages(prior_messages or [])

    # Opening: every seat answers independently
    yield {"type": "answers_start"}
    answers, answer_failures = await collect_answers(
        question, history=history, web_search=web_search
    )
    yield {"type": "answers_complete", "data": answers,
           "failures": answer_failures}

    if not answers:
        details = "; ".join(f"{f['model']}: {f['error']}" for f in answer_failures)
        yield {
            "type": "summary",
            "data": {
                "answers": [], "reviews": [],
                "ruling": {"model": "error",
                           "text": f"All council models failed to respond. {details}"},
            },
            "metadata": {"failures": {"answers": answer_failures, "reviews": []},
                         "mode": mode, "web_search": web_search},
        }
        return

    # Review: blind refereeing (full mode only, and only with two answers or more)
    reviews: List[Dict[str, Any]] = []
    review_failures: List[Dict[str, str]] = []
    authors: Dict[str, str] = {}
    standings: List[Dict[str, Any]] = []

    if mode != "quick" and len(answers) >= 2:
        yield {"type": "reviews_start"}
        reviews, authors, review_failures = await collect_reviews(
            question, answers, history=history
        )
        standings = tally_standings(reviews, authors)
        yield {
            "type": "reviews_complete",
            "data": reviews,
            "failures": review_failures,
            "metadata": {"authors": authors,
                         "standings": standings},
        }

    # Ruling: the chair settles it
    yield {"type": "ruling_start"}
    ruling = await chair_ruling(
        question, answers, reviews,
        authors=authors,
        standings=standings,
        history=history,
    )
    yield {"type": "ruling_complete", "data": ruling}

    # The summary is the authoritative record of the exchange: it is what gets
    # persisted, so a reloaded conversation carries everything the live one did.
    yield {
        "type": "summary",
        "data": {"answers": answers, "reviews": reviews, "ruling": ruling},
        "metadata": {
            "authors": authors,
            "standings": standings,
            "failures": {"answers": answer_failures, "reviews": review_failures},
            "usage": _sum_usage(
                [r.get("usage") for r in answers],
                [r.get("usage") for r in reviews],
                [ruling.get("usage")],
            ),
            "mode": mode,
            "web_search": web_search,
        },
    }


async def run_council(
    question: str,
    prior_messages: Optional[List[Dict[str, Any]]] = None,
    mode: str = "full",
    web_search: bool = False,
) -> Tuple[List, List, Dict, Dict]:
    """
    Run one deliberation to the end and return it whole.

    Returns (answers, reviews, ruling, metadata) — the contents of the summary
    event, for a caller that does not want the stream.
    """
    summary: Dict[str, Any] = {}
    async for event in run_council_stream(
        question, prior_messages=prior_messages, mode=mode, web_search=web_search
    ):
        if event["type"] == "summary":
            summary = event

    data = summary.get("data", {})
    return (data.get("answers", []), data.get("reviews", []),
            data.get("ruling", {}), summary.get("metadata", {}))
