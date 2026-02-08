# 6. Shared processor module

Date: 2025-01-01

## Status

Accepted

## Context

Multiple agents need the same utility functions: `_extract_json` (parse
structured JSON from Gemini's sometimes-messy output) and `_inject_tokens`
(insert token usage counts into YAML frontmatter). Duplicating these across
agent modules would create maintenance risk — a bug fix in one copy could
easily be missed in another.

## Decision

Keep shared Gemini utility functions in a central `processor.py` module.
Agents import what they need without depending on each other.

## Consequences

- Single source of truth for JSON extraction and token injection logic.
- Agents remain decoupled — they depend on `processor.py` but not on
  each other.
- `processor.py` must stay focused on genuinely shared utilities. Agent-specific
  logic belongs in the agent module, not here.
