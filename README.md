# Upwork Proposal Agent

An agentic loop that turns Upwork job postings into proposal drafts built
entirely on verified claims — and asks for human approval at every step
before anything reaches a client.

## Why this project exists

This is a real tool that Károly actually uses to write Upwork proposals. It
is also proof of how an agentic loop is built with Claude Code: skills, a
validating subagent, a blocking hook, and a custom MCP server that serves
the underlying facts (real professional experience) and logs every
decision.

## The non-negotiable principle

**No claim may reach the final proposal text unless it is backed by real
evidence.** This is not a theoretical requirement — it guards against a
specific past mistake (during an earlier Upwork application, the temptation
came up to reference a reference project that didn't actually exist). The
validation layer structurally rules this out: every substantive claim must
cite a concrete `experience_profile.json` entry (`source_ref`), and the
validator rejects anything that doesn't.

## The loop

```
Job posting text
        │
        ▼
   [PLAN]  the draft-proposal skill reads the posting
        │  + fetches experience_profile.json via the MCP server
        ▼
   [ACT]   writes the proposal draft, tying every substantive
        │  claim back to a concrete profile entry (source_ref)
        ▼
   [VALIDATE]  the proposal-validator subagent checks:
        │       - does every claim have a real, existing source_ref?
        │       - are there any banned generic phrases?
        │       - are all 7 required structural elements present?
        │       - length and tone rules
        ├── FAIL, retries left → [RETRY] targeted fix → back to VALIDATE
        │                        (max 2 automatic passes)
        ▼ PASS, or retries exhausted
   [ESCALATE / HUMAN GATE]  a hook halts the process, prints the draft +
        │  validation report, and waits for an explicit "APPROVED"
        │  (refused unless the report passed), "EDIT: ...", or
        │  "REJECTED" / "REJECTED: <reason>" input
        ├── EDIT → back to ACT
        ├── REJECTED → [LOG] (stop here)
        ▼ APPROVED
   [LOG]   the decision + final text is appended to proposal_log.json
```

### The steps, briefly

1. **PLAN** — the `draft-proposal` skill reads the job posting text and
   fetches Károly's real professional profile via the MCP server's
   `get_experience` tool.
2. **ACT** — writes the proposal draft following the 7-part structure,
   tying every substantive claim to a concrete `experience_profile.json`
   entry.
3. **VALIDATE** — the `proposal-validator` subagent structurally checks the
   draft: whether every `source_ref` is real, whether any banned phrases
   are present, whether the structure is complete, the length, and whether
   every concrete question the posting asks (rate, availability, residency)
   is answered. On failure, a targeted fix pass follows, then re-validation
   — capped at 2 automatic attempts, after which the still-failing draft
   goes to the same human gate as a passing one would (see below), just
   without `APPROVED` on the menu.
4. **ESCALATE / HUMAN GATE** — `pre-submit-gate.py` blocks the process until
   Károly gives an explicit `APPROVED`, `EDIT: ...`, or `REJECTED` /
   `REJECTED: <reason>` response — `APPROVED` only if the draft actually
   passed validation. Nothing may reach "submit-ready" status
   without human approval, and nothing is sent just because it wasn't
   explicitly rejected either.
5. **LOG** — the final decision and text are appended to
   `proposal_log.json` via the `log_decision` MCP tool.

## File structure

```
upwork-proposal-agent/
├── README.md
├── .claude/
│   ├── skills/
│   │   └── draft-proposal/
│   │       └── SKILL.md
│   ├── agents/
│   │   └── proposal-validator.md
│   └── hooks/
│       └── pre-submit-gate.py
├── mcp-server/
│   └── profile_store/
│       ├── server.py
│       └── data/
│           ├── experience_profile.example.json
│           ├── experience_profile.json          (git-ignored, personal)
│           ├── proposal_log.json.example
│           └── proposal_log.json                (git-ignored, personal)
├── schemas/
│   └── proposal_schema.json
└── examples/
    └── sample_run.md
```

## Developer notes

- `experience_profile.json` is the single source of truth for professional
  experience. It is extended only by hand, by Károly.
- The MCP server uses the Python `mcp` SDK with stdio transport.
- The optional FastAPI wrapper exposes the same five tools
  (`get_experience`, `get_past_proposals`, `get_proposal_detail`,
  `issue_gate_token`, `log_decision`) over HTTP.

## Design decisions

**`get_past_proposals` never returns full proposal text.** As
`proposal_log.json` grows over time, a tool that dumps the entire history
back into the skill's context on every call would become an unbounded,
ever-growing cost — most of it irrelevant to the job posting at hand.
Instead, `get_past_proposals` returns only small summaries (id, decision,
rate, a one-line summary) for a capped, paginated `limit` of the most
recent entries, sorted newest first. The full record for one specific past
proposal — including its complete draft — is only ever a
`get_proposal_detail(proposal_id)` call away, and `draft-proposal` is
instructed to reach for it only when there's a concrete reason (see
`SKILL.md`), not reflexively for every summary it sees. This is a plain
storage/pagination decision, not a retrieval-relevance one — filtering by
keyword uses a simple case-insensitive substring match, deliberately not
embeddings or an external search service.

**`log_decision` refuses an `"approved"` decision without a `gate_token`.**
`pre-submit-gate.py` is what actually blocks on a real human response, but
nothing used to stop some other code path from calling `log_decision`
directly with `decision="approved"`, skipping the gate entirely — a
convention, not an enforced rule. Now `issue_gate_token(proposal_id)`
hands out a single-use, 5-minute token, and only `log_decision` calls that
include a valid, matching, unexpired one may log `"approved"` (`"edited"`
and `"rejected"` don't need one — they don't claim final approval). Be
precise about what this does and doesn't guarantee: since the same agent
process runs both the gate script and any tool call, this cannot
cryptographically prove a human genuinely typed the response — an agent
that deliberately chose to replicate the token logic could still forge one.
What it does close is the realistic failure mode: an accidental or
future-code-path call to `log_decision(decision="approved")` that skips
the gate now fails immediately with a clear error, instead of silently
succeeding. The harder guarantee was already structural and remains
unchanged regardless of this mechanism: nothing in this codebase can submit
to Upwork — that stays a manual, human-only action outside the tool's
reach.

**Greeting placement is conditional, not templated.** Some postings dictate
the literal first words of the proposal (e.g. "start with MVP READY" as a
screening filter); a fixed "Hi," prefix would either duplicate or fight
that instruction. So the required opening phrase, if any, and the
salutation both live in one `greeting` field — the phrase always comes
first, the salutation right after — rather than the hook hard-coding a
static greeting. `sign_off` is similarly generated per draft (matching the
posting's register: "Best regards," / "Best," / "Cheers,") rather than
fixed, since a static choice would misread a casual startup posting or an
enterprise one about half the time. Neither field counts toward the
150-350 word length check — they're not the argument, and padding them
shouldn't let a draft dodge that check — but both are still scanned for
banned phrases, since "Dear Sir/Madam" is exactly the kind of phrase that
would otherwise sneak in specifically through the greeting.

**`pre-submit-gate.py` also serves the retry-cap escalation, not just the
final approval.** After `draft-proposal`'s 2 automatic retries, the
original design just had the skill "stop and ask" the user directly in
conversation — but that answer never went anywhere: `log_decision` was
never called, so `proposal_log.json` would show no record of a draft that
was given up on. The fix isn't a second gate — it's letting this one
accept a failing report too. `APPROVED` is refused whenever
`status != "pass"` (both in the interactive prompt and, redundantly, in
`main()` for `--test-mode`, which bypasses the prompt's own loop), but
`EDIT`/`REJECTED` work exactly as they do on a passing draft, since
neither can let anything unvalidated through — rejecting or editing a
failing draft is never the unsafe half of this system. Every human
decision this loop can produce, whatever the report said, now goes
through the one logged channel instead of some falling through as an
unrecorded conversational aside.

## Setup

```
make install
```

This creates a virtualenv, installs dependencies, and bootstraps the two
personal data files from their tracked examples if they don't already
exist locally:

- `mcp-server/profile_store/data/experience_profile.json` ← copied from
  `experience_profile.example.json` (one neutral placeholder entry) —
  **replace it with your own real, evidence-backed experience before using
  this for real proposals.**
- `mcp-server/profile_store/data/proposal_log.json` ← copied from
  `proposal_log.json.example` (`{"entries": []}`).

Neither real file is ever committed to git (see `.gitignore`): the first
holds personal professional information, and the second accumulates real
job postings, real proposal text, and real client-facing decisions once
the tool is in use. Only the neutral example files are tracked, so the
repo can be shared or published (e.g. as a portfolio piece) without
leaking either. If a real file is ever accidentally deleted locally,
re-run `make install` to restore the (empty/placeholder) starting point —
never restore it from git history, since it was never there.

Other useful targets: `make test` (pytest), `make lint` (ruff check +
format check), `make format` (auto-format with ruff), `make clean` (remove
the venv and caches).
