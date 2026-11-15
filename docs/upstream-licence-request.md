# Draft: licence request to the upstream project

Post this yourself, from your own GitHub account, as a new issue on
<https://github.com/karpathy/llm-council/issues>.

Check the existing issues first — if someone has already asked, add a short
`+1` with one line on what you built instead of opening a duplicate. A
thread with several people asking is more persuasive than three separate
threads.

---

**Title:**

```
Consider adding a LICENSE file
```

**Body:**

```
Thank you for putting this out. The anonymised peer review with self-vote
exclusion is a genuinely good idea and it has been more useful than the
weekend it took you suggests.

The repository currently has no LICENSE file, which means default copyright
applies and derivative work can't be redistributed. A number of us have
built substantially on the idea and would like to publish our versions with
proper attribution back to you.

Would you consider adding MIT or Apache-2.0? It would take a minute and
would unblock everyone who wants to build on this openly.

Either way, thank you for the weekend you spent on it.
```

---

## Notes on doing this well

**Say nothing else.** No mention of GST, India, your firm, or what you have
built. The moment the request reads as "please help my product", it becomes
a favour he has to evaluate rather than a housekeeping item he can close in
thirty seconds. Keep it about the repository.

**Do not ask for endorsement, review or partnership.** He has publicly said
he will not support the project. Asking for anything beyond a licence file
invites a no.

**Expect silence.** Twenty-three thousand stars generate a great deal of
noise. Silence is not refusal, and it is not personal. Do not follow up more
than once, and not sooner than a month.

**If he adds a licence**, thank him in the thread, in one line, and update
the NOTICE file here to reflect it. That is also the moment — and only then
— to mention what you built, briefly, if the conversation invites it.

**The fallback has since been exercised, which makes this request far less
pressing — but it is still worth making.** The inherited implementation has
been rewritten: the transport layer, the storage layer, every prompt, the
general council's route handlers and the launch script were each
reimplemented. No prompt, comment, docstring or sentence of documentation
from upstream is left.

What is left is the general council's vocabulary — the upstream function
names, the `stage1` / `stage2` / `stage3` keys, the "Response A" labels, the
fields of a stored conversation — together with imports, library calls, tool
output and blank lines. The vocabulary was that author's choice rather than
anything a library imposed, and it is kept because the API, the tests and
every stored conversation are written against it. `git blame` put the whole
remainder at 489 byte-identical lines on 15 November 2026; the breakdown is
in [upstream-provenance.md](upstream-provenance.md).

A licence from upstream would put that remainder beyond question, which is
the reason to ask. The MIT License here is granted over this project's own
work either way, and claims nothing in what the upstream author wrote.

The acknowledgement in NOTICE is not conditional on any of that and stays
permanently: the idea — several models answering, refereeing one another
blind, and a chair settling it — is Andrej Karpathy's, and a rewrite changes
whose lines are in the file, not whose insight started this.
