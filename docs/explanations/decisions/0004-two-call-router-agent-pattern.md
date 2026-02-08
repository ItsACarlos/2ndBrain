# 4. Two-call router-agent pattern

Date: 2025-01-01

## Status

Accepted

## Context

The system needs to handle several distinct message types — filing content,
querying the vault, editing existing notes, managing directives, and answering
general questions. A single monolithic Gemini prompt that both classifies the
message *and* executes every possible action would need to include all
formatting instructions, vault query logic, and edit planning in one call.
This makes the prompt fragile, hard to test, and wasteful of tokens.

## Decision

Split processing into two stages: a lightweight **router** call (~200 tokens)
that classifies intent and extracts metadata, followed by a specialised
**agent** call with a focused prompt tailored to that specific task.

## Consequences

- Each agent has a small, testable prompt that only includes instructions
  relevant to its task.
- Simple questions are answered in a single call (the router includes the
  answer directly), avoiding unnecessary second calls.
- Adding new capabilities means adding a new agent — the router prompt
  rebuilds itself dynamically from registered agent descriptions.
- The trade-off is two Gemini calls for filing/query/edit operations, but
  the router call is cheap and the overall token usage is lower than a
  combined prompt would be.
