# What is still in common with upstream, and how it was counted

`NOTICE` and the README say what this project still shares with
[karpathy/llm-council](https://github.com/karpathy/llm-council), which carries
no licence file. This note is the working behind those statements, so that
they can be checked rather than believed.

It records a measurement taken on **15 November 2026**. It is not a legal
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

## The result

| | Lines |
|---|---|
| Byte-identical to upstream before the pass of 15 November 2026 | 616 |
| Rewritten in that pass because they were expressive | 82 |
| Removed along with them (blank lines and brackets inside rewritten blocks, two unused template logos) | 45 |
| **Byte-identical to upstream now** | **489** |

Every one of the 489 falls into one of three classes.

| Class | Lines | What it is |
|---|---|---|
| Blank and structural | 279 | Blank lines, brackets, docstring delimiters, `Returns:`, code fences, and in `CLAUDE.md` a few bare section headings and file-name labels |
| Library and tool | 169 | Import statements; FastAPI, httpx, fetch and React calls; files a tool generated (the Vite React template, the uv manifests) |
| Upstream names | 41 | Function signatures, schema fields, dictionary keys and one-line statements built from the general council's vocabulary |

Nothing in the 489 is a prompt, a comment, a docstring or a sentence of
documentation.

## By file

| File | Lines | Blank and structural | Library and tool | Upstream names |
|---|---|---|---|---|
| `backend/council.py` | 78 | 65 | 0 | 13 |
| `backend/main.py` | 69 | 42 | 12 | 15 |
| `CLAUDE.md` | 48 | 48 | 0 | 0 |
| `README.md` | 36 | 35 | 1 | 0 |
| `frontend/eslint.config.js` | 29 | 1 | 28 | 0 |
| `backend/storage.py` | 29 | 18 | 3 | 8 |
| `frontend/package.json` | 28 | 0 | 28 | 0 |
| `frontend/src/api.js` | 25 | 20 | 5 | 0 |
| `frontend/.gitignore` | 24 | 2 | 22 | 0 |
| `backend/openrouter.py` | 20 | 13 | 2 | 5 |
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
| **Total** | **489** | **279** | **169** | **41** |

Lock files, outside the count: `frontend/package-lock.json` 3,760 lines and
`uv.lock` 661, both written by a package manager.

## The upstream names, and why they are still here

This is the class that is not dictated by anything. The general council keeps
the upstream vocabulary:

- function names — `stage1_collect_responses`, `stage2_collect_rankings`,
  `stage3_synthesize_final`, `calculate_aggregate_rankings`,
  `parse_ranking_from_text`, `generate_conversation_title`, `query_model`,
  `query_models_parallel`, and the conversation functions in `storage.py`;
- data keys — `stage1`, `stage2`, `stage3`, `label_to_model`,
  `aggregate_rankings`, and the `id` / `created_at` / `title` / `messages`
  fields of a stored conversation;
- the `Response A`, `Response B` labels a referee is shown;
- the three-stage order itself, which is the idea `NOTICE` credits.

Those were the upstream author's choices. They are kept because they are an
interface: `tests/test_council.py` imports the functions by name, the UI reads
the keys off the event stream, and every conversation already on disk is
stored in that shape. Renaming them is possible, but it is a data migration
and an API change, not a rewording.

`git blame` understates this class. It counts a line only where the whole
line is unchanged, so a renamed parameter beside an upstream function name
does not register. The list above is the fuller statement; the 41 is only the
part of it that blame can see.

## What the pass of 15 November 2026 rewrote

- the conversation-title prompt in `backend/council.py`, and the line that
  labels each answer in the chairman's prompt;
- the module docstrings of `backend/council.py`, `backend/main.py` and
  `backend/__init__.py`, and the upstream comments in `backend/config.py` and
  `.gitignore`;
- the general council's route handlers in `backend/main.py`, whose bodies had
  come across as whole blocks;
- `update_conversation_title` in `backend/storage.py`, likewise;
- `start.sh`, which had come across whole;
- four lines of upstream prose in each of `README.md` and `CLAUDE.md`.

Behaviour was held fixed: the test suite passes unchanged, and a scripted
conversation run against the commit before and the commit after — both
routes, both modes, a failing model, a title past the length limit, a missing
conversation — produced the same output apart from the prompt text itself.

Two files were deleted rather than rewritten: `frontend/public/vite.svg` and
`frontend/src/assets/react.svg`. They were the Vite template's logos, nothing
referenced them, and they belong to neither this project nor upstream.

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
four are meant to say the same thing.
