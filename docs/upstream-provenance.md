# What is still in common with upstream, and how it was counted

`NOTICE` and the README say what this project still shares with
[karpathy/llm-council](https://github.com/karpathy/llm-council), which carries
no licence file. This note is the working behind those statements, so that
they can be checked rather than believed.

It records a measurement taken on **16 November 2026**. It is not a legal
opinion, and it does not say whether anything in the remainder is protectable.

## The measure

The upstream commits are part of this repository's own history, so
`git blame` shows which lines are still byte-identical to them:

```bash
git blame --line-porcelain -- <file> | grep -c '^author karpathy'
```

Run over every tracked text file, with the two lock files set aside (they are
generator output and are counted separately below). A full clone is needed:
on a shallow clone `git blame` cannot see the upstream commits and reports
nothing.

`git blame` only sees a line that is unchanged in full. Two further checks
were run for what it misses, and both are described under "What blame cannot
see" below.

## The result

| | Lines |
|---|---|
| Byte-identical to upstream at the start | 616 |
| After the first pass, 15 November 2026 — expressive lines rewritten | 489 |
| After the second pass, 16 November 2026 — the general council renamed | 457 |
| **Byte-identical to upstream now** | **457** |

Every one of the 457 falls into one of three classes.

| Class | Lines | What it is |
|---|---|---|
| Blank and structural | 270 | Blank lines, brackets, docstring delimiters, code fences, and in `CLAUDE.md` a few bare file-name labels |
| Library and tool | 169 | Import statements; FastAPI, httpx, fetch and React calls; files a tool generated (the Vite React template, the uv manifests) |
| Ordinary names | 18 | Field names any conversation record has (`id`, `created_at`, `title`, `messages`), parameter names (`model`, `messages`, `conversation_id`), return annotations, and one line that uses the `CHAIRMAN_MODEL` setting |

Nothing in the 457 is a prompt, a comment, a docstring or a sentence of
documentation, and none of it carries the `stage1` / `stage2` / `stage3`
vocabulary.

## By file

| File | Lines | Blank and structural | Library and tool | Ordinary names |
|---|---|---|---|---|
| `backend/council.py` | 68 | 64 | 0 | 4 |
| `backend/main.py` | 62 | 42 | 12 | 8 |
| `CLAUDE.md` | 43 | 43 | 0 | 0 |
| `README.md` | 33 | 32 | 1 | 0 |
| `frontend/eslint.config.js` | 29 | 1 | 28 | 0 |
| `frontend/package.json` | 28 | 0 | 28 | 0 |
| `frontend/src/api.js` | 25 | 20 | 5 | 0 |
| `frontend/.gitignore` | 24 | 2 | 22 | 0 |
| `backend/storage.py` | 24 | 18 | 3 | 3 |
| `backend/openrouter.py` | 18 | 13 | 2 | 3 |
| `.gitignore` | 17 | 4 | 13 | 0 |
| `frontend/src/App.jsx` | 12 | 7 | 5 | 0 |
| `backend/config.py` | 12 | 7 | 5 | 0 |
| `frontend/index.html` | 11 | 0 | 11 | 0 |
| `pyproject.toml` | 10 | 0 | 10 | 0 |
| `start.sh` | 9 | 5 | 4 | 0 |
| `frontend/src/main.jsx` | 9 | 1 | 8 | 0 |
| `frontend/vite.config.js` | 7 | 1 | 6 | 0 |
| `frontend/README.md` | 7 | 7 | 0 | 0 |
| `frontend/src/App.css` | 5 | 1 | 4 | 0 |
| `main.py` | 3 | 2 | 1 | 0 |
| `.python-version` | 1 | 0 | 1 | 0 |
| **Total** | **457** | **270** | **169** | **18** |

Lock files, outside the count: `frontend/package-lock.json` 3,760 lines and
`uv.lock` 661, both written by a package manager.

## What the two passes did

**First pass — the expressive lines.** 82 of the original 616 were prompts,
comments, docstrings, prose, or handler bodies that had come across as whole
blocks: the conversation-title prompt, three module docstrings, the general
council's route handlers, `start.sh`, and upstream sentences in the README and
`CLAUDE.md`. All were rewritten with behaviour held fixed. Two unused Vite
template logos were deleted, since they belonged to neither this project nor
upstream.

**Second pass — the vocabulary.** The general council had kept the upstream
names, which were that author's choices and not something a library imposed.
They were replaced with this project's own, built on what the three parts of
an exchange are: its answers, its reviews and its ruling.

| What | Was | Is now |
|---|---|---|
| Deliberation functions | `stage1_collect_responses`, `stage2_collect_rankings`, `stage3_synthesize_final` | `collect_answers`, `collect_reviews`, `chair_ruling` |
| | `parse_ranking_from_text`, `calculate_aggregate_rankings` | `read_order_of_merit`, `tally_standings` |
| | `generate_conversation_title`, `run_full_council` | `title_for_conversation`, `run_council` |
| Transport | `query_model`, `query_models_parallel` | `ask_model`, `ask_models` |
| Storage | `create_` / `get_` / `save_conversation`, `list_conversations` | `open_` / `read_` / `write_conversation`, `conversation_index` |
| | `add_user_message`, `add_assistant_message`, `update_conversation_title` | `record_question`, `record_exchange`, `retitle_conversation` |
| Stored exchange | `stage1`, `stage2`, `stage3` | `answers`, `reviews`, `ruling` |
| Inside it | `response`; `ranking`, `parsed_ranking` | `text`; `assessment`, `order` |
| Metadata | `label_to_model`, `aggregate_rankings`, `average_rank`, `rankings_count` | `authors`, `standings`, `mean_position`, `reviews_counted` |
| Stream events | `stage1_start` … `stage3_complete`, `title_complete` | `answers_start` … `ruling_complete`, `conversation_titled` |
| Request field | `content` | `question` |
| Answer labels | "Response A" | "Answer A" |
| Frontend client | `listConversations`, `createConversation`, `getConversation`, `sendMessageStream` | `conversationIndex`, `openConversation`, `readConversation`, `askCouncil` |

This pass changed behaviour, deliberately: the general council's API and its
stored format are different from what they were. See "Conversations stored
before the renaming" below.

## What is still shared, and why

- **The idea and its shape.** Several models answer, referee one another
  blind, and a chair settles it. `NOTICE` credits it and nothing here claims
  it.
- **Configuration names.** `COUNCIL_MODELS`, `CHAIRMAN_MODEL`, `DATA_DIR`,
  `OPENROUTER_API_KEY` and `OPENROUTER_API_URL`. The first three and the key
  are environment variables that running deployments are configured with, in
  `render.yaml`, the `Dockerfile` and operators' own settings. Renaming them
  would break a live deployment at its next restart, for a name.
- **The `/api/conversations` routes** and the ordinary field names of a
  conversation record: `id`, `created_at`, `title`, `messages`, and the
  `role` / `content` shape of a chat message, which is the model API's own.
- **The compliance panel's event names.** Its stream uses `stage1_complete`
  and the like for its own five stages. It is a different protocol with its
  own clients and tests, and it was left alone.
- **One translation table.** `backend/storage.py` lists the old keys beside
  the current ones, because that is how an old record is read.

## What blame cannot see

A line that was edited is no longer attributed to upstream, however little
changed. Two checks were run against every line upstream ever committed:

- an exact comparison ignoring leading whitespace, which finds lines that were
  removed and typed again, or moved;
- a similarity comparison at line and at sentence level, which finds close
  paraphrases.

They found a paraphrase of the upstream README's description of the council,
three sentences in `CLAUDE.md`, one comment and one error message. All were
rewritten in the second pass. What the checks still match is import
statements, shell commands, URLs and section headings.

## Conversations stored before the renaming

They are on disk in the old shape and were not rewritten by the change.

- `storage.read_conversation` upgrades a record as it is read, so the
  application and its API only ever see the current shape. A file is rewritten
  the next time its conversation is added to.
- `python -m backend.cli migrate-conversations` reports how many files are in
  the old shape; with `--apply` it rewrites them. Each rewrite is an atomic
  replace, so an interrupted run can be run again.
- Only keys are translated. A record keeps the labels it was written with —
  "Response A" in an old one — because the stored assessments quote them and
  the `authors` map beside them is what gives them meaning.
- A release from before the renaming cannot read a record once it has been
  rewritten. Rolling back after `--apply`, or after users have added to old
  conversations, needs the data restored as well as the code.

## `header.jpg`

Not the upstream image. Upstream's was a 1024×506 illustration of the generic
council; it was replaced on 26 July 2026 by the 2048×1150 diagram of the
compliance panel now in the repository, drawn for this project.

## Running it again

```bash
for f in $(git ls-files); do
  file -b --mime "$f" | grep -q 'charset=binary' && continue
  n=$(git blame --line-porcelain -- "$f" | grep -c '^author karpathy')
  [ "$n" -gt 0 ] && echo "$n $f"
done | sort -rn
```

The figure should only fall. If it is re-run after further changes, update the
numbers here and in `NOTICE`, the README and
[upstream-licence-request.md](upstream-licence-request.md) together — the
four are meant to say the same thing, and a test in
`tests/test_deployment.py` fails if they stop.
