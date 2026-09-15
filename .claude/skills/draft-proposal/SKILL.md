---
name: draft-proposal
description: Writes an Upwork proposal draft from a job posting, following the proposal_schema.json structure, tying every substantive claim to a real experience_profile.json entry. Use when the user provides an Upwork job posting text and wants a proposal draft for it.
---

# draft-proposal

This skill writes a proposal draft from an Upwork job posting, following
the `schemas/proposal_schema.json` structure. The goal is not a "nice"
piece of writing — it's a **verifiable** one: every substantive claim must
be traceable to a specific, real piece of experience.

## Input

- The job posting text (plain text or markdown).
- Optional extra context from the user (e.g. a target rate, prior
  communication with the client).

## Steps

1. **Fetch the profile.** Call the MCP `profile_store` server's
   `get_experience` tool and retrieve the full `experience_profile.json`
   content. Don't work from memory or assumptions carried over from earlier
   runs — always fetch the current profile.

2. **Analyze the job posting.** Read it carefully. Identify:
   - what the client's *real* problem is (not just the task as stated on
     the surface, but what's behind it — e.g. "the pricing logic has become
     too complex" is not the same as "need a Magento developer")
   - what technical/business context the client is operating in
   - whether the posting explicitly asks for a specific answer (hourly
     rate, availability, residency, or another hard requirement)

3. **Check recent proposal history — lightly.** Call the MCP server's
   `get_past_proposals` tool with a small `limit` (the default, 5, is
   almost always enough — don't ask for a large limit "just in case"). Use
   it to check for useful context, e.g. whether a similar job was seen
   before or what rate was typically quoted. This call only ever returns
   lightweight summaries (never the full past proposal text), so it's cheap
   to make.
   - **Only call `get_proposal_detail(proposal_id)`** — which returns one
     past proposal's full text — when there's a concrete reason to: the
     `proposal-validator` or the user explicitly points at a specific past
     proposal, or a summary looks specifically relevant and you need the
     exact wording/rate from it. Never call it speculatively for every
     summary `get_past_proposals` returns — that defeats the entire point
     of the summary/detail split, which exists to keep this skill's own
     context usage bounded as the log grows over time.

4. **Write the draft.** The full shape is: `greeting` → the 7-part
   structure below → `sign_off`. Each claim should also read as a
   self-contained 1-2 sentence unit — the rendered draft puts each claim on
   its own line, not merged into the surrounding prose, so don't write one
   claim to grammatically flow into the next.

   **`greeting`** — the very first line of the whole proposal:
   - If the posting has an explicit required opening (e.g. "start your
     proposal with X"), that phrase comes first, verbatim, immediately
     followed by the salutation — e.g. `"MVP READY. Hi there,"`. Never
     repeat that phrase inside `opening_observation`; it belongs in
     `greeting` only.
   - If a client name is discoverable in the posting text, personalize it
     — `"Hi John,"` / `"Hello Sandra,"` — and vary the phrasing naturally
     rather than always using the same template.
   - If no name is discoverable and there's no required opening phrase,
     use a light, generic opener — `"Hi,"` / `"Hi there,"` / `"Hello,"` —
     and vary which one, don't default to the same one every time.

   **The 7-part structure** (pure content — `opening_observation` never
   carries a compliance phrase; that lives in `greeting`):
   1. **A strong observation** about the client's real problem — react to a
      concrete detail from the posting, not a generality.
   2. **Demonstrate understanding of the product/situation** — show that
      you understand what the client works on, in what system, in what
      context.
   3. **Highlight the ability to quickly understand complex systems** — tie
      this, and every further experience claim, to the relevant
      `experience_profile.json` entry as a `source_ref`.
   4. **A small insight or suggestion** that provides value on its own —
      something the client can act on immediately, regardless of whether
      they hire the applicant.
   5. **Smart question(s)** about what's actually blocking progress — not a
      generic question ("when would you like to start?"), but one derived
      from the specifics of the posting.
   6. **Positioning** as someone who brings stability and momentum — brief,
      fact-based, not self-promotional.
   7. **A natural, simple closing** — short, not a forced call-to-action.

   **`sign_off`** — just the phrase, not the name (the signer's name is
   appended automatically when the draft is rendered — never include it
   yourself). Match the posting's register: `"Best regards,"` for a more
   formal/corporate posting, `"Best,"` for a neutral one, `"Cheers,"` for a
   casual/startup one — use judgment, don't default to the same one every
   time.

5. **Source every substantive claim.** Any sentence that references
   experience, a skill, or past work must go into the
   `relevant_experience.claims[]` array with a `source_ref` field pointing
   to an existing `experience_profile.json` entry `id` (e.g. `exp-002`).
   - **If there is no matching profile entry for a claim, do not invent
     one.** There are two options: (a) drop the claim from the text, or
     (b) if the claim would matter to the strength of the proposal, flag it
     explicitly as "missing evidence" outside the JSON, at the end of your
     response, so the user knows this part cannot be substantiated without
     a human addition.
   - Don't copy the profile text verbatim — rephrase it for the job
     posting's context, but the factual content (company name, timeframe,
     technical detail) must stay exactly what's in the profile.

6. **Fill in required fields if the posting asks for them.** If the
   posting explicitly asks for an hourly rate, availability, or residency,
   fill in the `target_rate` / `availability` fields clearly. The fact of
   residency (`exp-007`) should only go into `relevant_experience` if the
   posting explicitly requires or asks about it.

7. **Banned elements — avoid:**
   - Generic, worn-out Upwork phrases: "I'd love to help", "I am confident
     that", "Dear Sir/Madam", "As an AI...". This applies to `greeting` and
     `sign_off` too, not just the 7-part content — "Dear Sir/Madam" is
     exactly the kind of phrase that would otherwise sneak in through the
     greeting specifically.
   - Huge, list-like skill dumps ("I have experience in: X, Y, Z, W, V, ...").
   - Over-polished, robotic, marketing-style tone. The goal is a
     competent, calm, specific tone — as if writing a technical assessment
     to a colleague.

8. **Meta fields.** Fill in the `meta` object:
   - `job_posting_hash`: a stable hash of the job posting text (e.g.
     `sha256:<hex>`).
   - `created_at`: ISO 8601 timestamp.
   - `status`: `"draft"` — always this before validation and approval.

## Output

A JSON object exactly matching the `schemas/proposal_schema.json` schema
(`greeting` and `sign_off` are required fields alongside the 7-part
content — note that `greeting`/`sign_off` don't count toward the 150-350
word length check, so don't pad them to affect it). After the JSON, if any
evidence was missing, list it in a separate section: "Missing evidence:
<description of the claim> — no matching experience_profile entry, please
add one manually if relevant."

## Retry case

If the `proposal-validator` subagent returns a `fail` status, don't rewrite
the whole draft from scratch. Read the `issues[]` list and fix the flagged
fields/problems in a targeted way (e.g. replace an invalid `source_ref`
with a real one, or drop that claim; shorten the text if it's too long; add
the missing rate if the posting asked for one). Submit the corrected draft
for re-validation.

**Retry cap: 2 automatic correction passes, then stop and ask.** This isn't
a safety limit — `pre-submit-gate.py` independently blocks anything that
isn't `status: "pass"`, no matter how many retries happened, so a stuck
loop can never let unvalidated text through. It's a cost/time limit: after
2 failed validation attempts on the same draft, don't attempt a 3rd
automatic rewrite. Instead, show the current draft and the unresolved
`issues[]` as they stand, and ask the user how to proceed (e.g. relax a
rule, provide the missing information yourself, or accept a specific
trade-off) rather than continuing to loop on your own.
