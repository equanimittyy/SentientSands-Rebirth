# Sentient Sands Rebirth

## What this project is

Sentient Sands Rebirth is a Kenshi mod that uses LLMs to drive NPC dialogue, character profiles, and world events. It has three parts: a C++ plugin (`plugin/`, built to `SentientSands.dll`) that runs inside the game through RE_Kenshi and KenshiLib, a local Python Flask server (`server/`) that builds prompts and calls an OpenAI-compatible provider, and the Kenshi mod files (`mod/`). `scripts/package_release.py` builds the release zip, which ships an embedded Python runtime, so players install nothing else.

[docs/info/architecture.md](docs/info/architecture.md) holds the layout, the path and transport contracts between the plugin and the server, and the threading rule. Read it before you change how the two sides find or talk to each other. [docs/info/development.md](docs/info/development.md) covers building, running, and releasing.

The C++ plugin builds only on Windows with the Visual C++ 2010 toolset (`plugin/SentientSands.vcxproj`), so you cannot build it in the dev container. The container has `python3` but no `pip`, and its firewall blocks PyPI, so the server's dependencies (`flask`, `requests`) are not installed there either.

## Working method

Bias to caution over speed; when in doubt these beat momentum.

1. **Think before coding.** State assumptions. Surface multiple interpretations instead of silently picking one; if it's unclear, ask — don't infer and commit. Name a simpler approach before building the complex one.
2. **Simplicity first.** Minimum code that solves the stated problem. No speculative features, single-use abstractions, unrequested config, or guards for impossible cases. If the diff is 200 lines and the problem needed 50, rewrite it.
3. **Surgical changes.** Touch only what the task requires. Don't reformat or refactor adjacent code; match existing style. Remove orphans your edit creates; flag *pre-existing* dead code, don't silently delete it.
4. **Goal-driven.** Turn fuzzy asks into verifiable outcomes first: "add validation" → tests for invalid inputs; "fix the bug" → a failing repro that goes green. State a brief step → verify plan for multi-step work.
5. **Errors are yours.** Build / typecheck / lint / test failures surfaced during your work are yours to fix or escalate. "Pre-existing" and "unrelated" are deferrals, not diagnoses: if a failure truly predates your diff, say so concretely and ask — don't wave it away.
6. **Commits are explicit-only.** Never `git commit` / `push` unless asked *this turn*; "implement / fix / finish X" means do the work and leave it in the tree for review. Approval for one commit doesn't carry to the next. Before staging, sweep each touched file (not just the diff) for comments that fail the §Documentation & comments bar. When authorised: Conventional Commits (`feat` / `fix` / `docs` / `refactor` / `chore` / `test`, optional scope); a subject naming the change, and a *why*-focused body only where the diff doesn't show the reason. Write the body as Markdown bullets (`- `), one fact per bullet — never prose paragraphs. Each bullet is one physical line (never hard-wrap — it breaks the Markdown render), ≤400 chars.
7. **Ticket close-out.** Finish every Actionable before starting anything else. Then post an ELI5 comment on the issue — plain-language what was done and why, in the §Voice framing. Then surface the ticket's Adhoc items to the user as a batch; they pick each one's fate (ticket elsewhere / do now / veto). Never action an adhoc yourself.

## Documentation & comments

Decided things only. Explain **why, never what** — the reader can read the code. Never cite a tracking ID or origin tag (ticket / run / finding / PR, `#1234`, run-dates): they rot; describe the failure mode or constraint directly.

Keep CLAUDE.md slim (purpose + rules; update only when the project's purpose or feel changes). Reference docs hold decided things — speculation goes to the tracker, not prose; update the doc in the same change that alters what it describes. No work-tracking checklists in markdown; backlog and status live on the board.

**Comments** — default none; the bar to add one is high (deleting needs no reason, adding does). First fix the name or split the function — a comment is the last resort, not the first. A line is earned *only* by a *why* the code can't show: a load-bearing invariant, a rejected alternative, a security / concurrency rationale, a non-obvious encoding, a bug's failure mode. Everything else is noise, cut on sight — restating the next line, narrating a branch or how the code got here, re-describing a visible mechanism, hedging, scene-setting, field-restating JSDoc, section banners, per-function / per-block reflexes, commented-out code, names, dates, emojis. One line; a file-top docblock may carry a longer *why* (the module's role, load-bearing invariants), kept tight. Delete any duplicate the docblock or a neighbour already states; when unsure, delete. Bad: `// loop the array`. Good: none, or `// Retry: API flakes under load`.

**Prose docs** keep file:line refs and cross-doc pointers (relative links, anchored to stable headings). Drop tracking citations, run-dated / origin-tagged headings, "last updated", restated titles, and "revisit later". One idea per paragraph; a table for 3+ parallel facts; a heading with no body is a TODO. Filenames are `lower_snake_case` (subdir docs get descriptive names, not `README.md`); `UPPER_CASE` only for repo-root `CLAUDE.md` / `README.md`. Smell test per addition: finish "a future reader won't know that…" — can't? Delete it.
