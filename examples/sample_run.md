# Sample run: full loop, one deliberately injected error

This document walks a single job posting through the entire loop end to end —
PLAN → ACT → VALIDATE → RETRY → VALIDATE → HUMAN GATE → LOG — including a
deliberately fabricated claim, to demonstrate that the validation layer
actually catches it rather than just existing on paper.

Every command below was actually run against the real `mcp-server/profile_store`
MCP server and the real `pre-submit-gate.py` hook in this repo (`--test-mode`
was used only to supply the human's "APPROVED" keystroke non-interactively for
this captured transcript — the code path is identical to a real interactive
run). `proposal_log.json` was reset back to `{"entries": []}` afterward so the
tool starts clean for Károly's actual use.

*Updated note:* the schema later grew two more required fields, `greeting`
and `sign_off` (see README's Design decisions) — the JSON below was updated
to include them so this stays a valid example against the current schema,
but this specific walkthrough predates that change; the greeting/sign_off
mechanism itself was verified separately (see the end-to-end demo referenced
in README).

## The job posting

```
AI Agentic Developer for B2B Platforms

We're building an agentic-AI platform for European B2B companies covering
pricing automation, quote generation, LLM-based email processing, and
ERP/CRM integrations — all with human-approval gates before any
consequential action goes through.

We're looking for a Claude Code power user: someone comfortable building
with subagents, skills, hooks, and MCP servers, not just prompting a
chatbot.

EEA residency is a hard requirement.

~40 hours/week starting September. This starts as a paid trial task before
a longer engagement.
```

`meta.job_posting_hash`: `sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e`

## 1. PLAN — fetching the profile

The `draft-proposal` skill calls the `profile_store` MCP server's
`get_experience` tool and gets back the full `experience_profile.json`
(7 entries: `exp-001` … `exp-007`). It does not invent an 8th entry — that
constraint is exactly what this run is designed to test.

## 2. ACT — first draft (with an intentionally injected error)

To prove the validator actually works, this first draft includes one claim
that reaches beyond the real profile: a claim about SAP/NetSuite ERP
integration work, tagged with `source_ref: "exp-008"` — an id that does not
exist anywhere in `experience_profile.json`.

```json
{
  "greeting": "Hi there,",
  "opening_observation": "Your posting is really about building trust into automation: pricing decisions, quote generation, and ERP/CRM writes are exactly the kind of actions that damage client relationships if an agent gets them wrong without a human checking first.",
  "problem_understanding": "You're not looking for someone to bolt an LLM onto existing workflows. You need an agentic system where every consequential action, a quote going out, a CRM record changing, passes through an explicit approval gate, built by someone who already works this way day to day rather than someone learning agent design on your budget.",
  "relevant_experience": {
    "claims": [
      {
        "text": "I've spent 15+ years working full-stack, largely on messy, pre-existing production systems, where the real job is understanding what's actually going on before changing anything. That's most of the work in wiring agentic automation into a live B2B pricing and quoting flow.",
        "source_ref": "exp-001"
      },
      {
        "text": "I built a B2B headless e-commerce platform on Saleor with a Python backend and React frontend as an independent contractor, so the B2B data model and pricing and catalog side of this isn't unfamiliar territory.",
        "source_ref": "exp-004"
      },
      {
        "text": "I use Claude Code daily for my own development work, subagents, skills, hooks and MCP servers included, which is the exact toolchain you're asking for rather than something I'd be picking up for this project.",
        "source_ref": "exp-006"
      },
      {
        "text": "I've directly integrated SAP and NetSuite ERP systems into automated quote-generation pipelines for enterprise clients.",
        "source_ref": "exp-008"
      },
      {
        "text": "I'm based in Budapest, Hungary, inside the EEA residency requirement you listed.",
        "source_ref": "exp-007"
      }
    ]
  },
  "insight_or_question": "One thing worth flagging before we even start: the riskiest part of this build usually isn't the LLM email processing, it's making the human-approval gate genuinely block, not just log and continue, on the ERP/CRM write path. That's where a race condition or a swallowed exception can quietly cause a duplicate order or a wrong price to go out. Which ERP or CRM are you integrating with first, and is there already a sandbox account for it, or would that need to be set up?",
  "closing": "Happy to walk through how I'd structure the approval-gate layer on a short call.",
  "sign_off": "Best regards,",
  "availability": "40 hours/week starting September.",
  "meta": {
    "job_posting_hash": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
    "created_at": "2026-09-14T09:00:00Z",
    "status": "draft"
  }
}
```

This validates fine against `schemas/proposal_schema.json` — the schema only
checks *shape*, not *truth*. Catching the fabricated `exp-008` reference is
the validator's job, not the schema's.

## 3. VALIDATE — the validator catches it

`proposal-validator` reads the draft above plus the real
`experience_profile.json`, and checks every `source_ref`:

```
valid ids in experience_profile.json: exp-001, exp-002, exp-003, exp-004, exp-005, exp-006, exp-007
claim[3].source_ref = "exp-008"  ->  NOT FOUND
```

Its output:

```json
{
  "status": "fail",
  "issues": [
    {
      "field": "relevant_experience.claims[3].source_ref",
      "problem": "'exp-008' does not exist in experience_profile.json. This claim references a SAP/NetSuite ERP integration that has no corresponding entry in the profile — it is a fabricated reference to work that was never done.",
      "suggestion": "Remove this claim entirely, since there is no real evidence for it in the profile. Do not substitute a different existing source_ref, because none of the current entries actually support an ERP integration claim of this kind."
    }
  ]
}
```

This is the exact failure mode the whole project exists to prevent: a claim
that sounds plausible and on-topic (the posting literally asks about ERP/CRM
integration) but has no real backing. The gate does not let it through.

## 4. RETRY — the corrected draft

Per the validator's `suggestion`, the ERP/CRM claim is removed outright — no
substitute `source_ref` is used, because no existing entry actually supports
it. Instead, the gap is turned into exactly the kind of "smart question"
structural element the proposal already needed (step 5 of the 7-part
structure), plus an honest, one-line disclosure:

```json
{
  "greeting": "Hi there,",
  "opening_observation": "Your posting is really about building trust into automation: pricing decisions, quote generation, and ERP/CRM writes are exactly the kind of actions that damage client relationships if an agent gets them wrong without a human checking first.",
  "problem_understanding": "You're not looking for someone to bolt an LLM onto existing workflows. You need an agentic system where every consequential action, a quote going out, a CRM record changing, passes through an explicit approval gate, built by someone who already works this way day to day rather than someone learning agent design on your budget.",
  "relevant_experience": {
    "claims": [
      {
        "text": "I've spent 15+ years working full-stack, largely on messy, pre-existing production systems, where the real job is understanding what's actually going on before changing anything. That's most of the work in wiring agentic automation into a live B2B pricing and quoting flow.",
        "source_ref": "exp-001"
      },
      {
        "text": "I built a B2B headless e-commerce platform on Saleor with a Python backend and React frontend as an independent contractor, so the B2B data model and pricing and catalog side of this isn't unfamiliar territory.",
        "source_ref": "exp-004"
      },
      {
        "text": "I use Claude Code daily for my own development work, subagents, skills, hooks and MCP servers included, which is the exact toolchain you're asking for rather than something I'd be picking up for this project.",
        "source_ref": "exp-006"
      },
      {
        "text": "I'm based in Budapest, Hungary, inside the EEA residency requirement you listed.",
        "source_ref": "exp-007"
      }
    ]
  },
  "insight_or_question": "One thing worth flagging before we even start: the riskiest part of this build usually isn't the LLM email processing, it's making the human-approval gate genuinely block, not just log and continue, on the ERP/CRM write path. That's where a race condition or a swallowed exception can quietly cause a duplicate order or a wrong price to go out. Which ERP or CRM are you integrating with first, and is there already a sandbox account for it, or would that need to be set up? I haven't personally shipped a SAP or NetSuite integration, so knowing the target system upfront would let me flag early where I'd need to ramp up versus where I can move fast.",
  "closing": "Happy to walk through how I'd structure the approval-gate layer on a short call.",
  "sign_off": "Best regards,",
  "availability": "40 hours/week starting September.",
  "meta": {
    "job_posting_hash": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
    "created_at": "2026-09-14T09:05:00Z",
    "status": "draft"
  }
}
```

Re-validating: every `source_ref` (`exp-001`, `exp-004`, `exp-006`, `exp-007`)
exists in the profile, no banned phrases are present, all 7 structural
elements are there, and the word count (claims + narrative fields, excluding
`greeting`/`sign_off`) is 347 — inside the 150–350 word range. Result:

```json
{
  "status": "pass",
  "issues": []
}
```

## 5. HUMAN GATE — `pre-submit-gate.py`

Running the real hook against the corrected draft and the passing report:

```
$ python .claude/hooks/pre-submit-gate.py --draft draft2.json --report report2.json
========================================================================
PROPOSAL DRAFT
========================================================================
[... full draft printed ...]

========================================================================
VALIDATION REPORT
========================================================================
Status: pass
No issues.

Approve this draft for submission?
  Type APPROVED to approve as-is, or
  Type EDIT: <what to change> to send it back for a rewrite.
> APPROVED
```

The process blocks on that prompt until an explicit `APPROVED` or
`EDIT: <instruction>` is typed — there is no timeout or default path. (Verified
separately: piping EOF into the hook instead of a real answer makes it exit
with `No input received (EOF) — the gate cannot proceed...` rather than
falling through to approval.)

On `APPROVED`, the hook sets the draft's `meta.status` to `"approved"`,
calls `issue_gate_token(proposal_id)` to get a single-use approval token,
and then calls the `profile_store` MCP server's `log_decision` tool for
real, passing the full structured draft (not just its rendered text) as
`draft`, plus that token. `log_decision` refuses to log `"approved"`
without a valid, matching token — see README's Design decisions section
for exactly what that does and doesn't guarantee.

The "paste this into Upwork" text the hook prints is `greeting`, then the
7-part content with each claim as its own paragraph (not merged into one
dense block), then `sign_off` plus the signer's name — see README's Design
decisions section for why the greeting/sign-off placement is conditional on
what the posting itself requires.

## 6. LOG — the resulting `proposal_log.json` entry

`log_decision` derives the lightweight summary fields
(`job_title_or_hash`, `target_rate`, `summary`) from the draft and stores
the draft itself as `full_draft`:

```json
{
  "proposal_id": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
  "decision": "approved",
  "job_title_or_hash": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
  "target_rate": null,
  "summary": "Your posting is really about building trust into automation: pricing decisions, quote generation, and ERP/CRM writes are exactly the kind o…",
  "full_draft": { "...the complete draft from step 4, with meta.status now \"approved\"...": "" },
  "notes": null,
  "logged_at": "2026-09-14T06:59:10.065815+00:00"
}
```

### Reading it back without flooding context: `get_past_proposals` vs. `get_proposal_detail`

`get_past_proposals()` (default `limit=5`) returns only the lightweight
fields above — **never** `full_draft`:

```json
{
  "results": [
    {
      "proposal_id": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
      "logged_at": "2026-09-14T06:59:10.065815+00:00",
      "job_title_or_hash": "sha256:dd0f2a0480a6cd17288aea451003ad6848d928ed3df057deeb5f91ba0603ce7e",
      "decision": "approved",
      "target_rate": null,
      "summary": "Your posting is really about building trust into automation: pricing decisions, quote generation, and ERP/CRM writes are exactly the kind o…"
    }
  ],
  "has_more": false,
  "total_matches": 1
}
```

The `draft-proposal` skill only escalates to
`get_proposal_detail(proposal_id)` — which returns this same record plus
the full `full_draft` and `notes` — when it actually needs one specific
past proposal in full (see `SKILL.md`). It does not do this for every
summary it sees.

## What this proves

- A fabricated claim (`exp-008`, an ERP integration that never happened) was
  actually written into a first draft, actually caught by the validator with
  a specific, correct diagnosis, and actually removed rather than patched
  over with a different fake reference.
- The corrected draft only ever cites real `experience_profile.json` entries.
- Nothing reached `"approved"` status without a real, blocking human
  keystroke — verified both for the approval path and for the "nothing typed"
  path.
- `log_decision` wrote a real record through the real MCP server, not a
  simulated one.
- `get_past_proposals` genuinely never returned `full_draft` — the
  lightweight summary above is exactly what the real tool call produced,
  not a hand-edited example.
