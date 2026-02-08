# 5. Metadata-only vault queries

Date: 2025-01-01

## Status

Accepted

## Context

The vault query agent needs to answer questions about previously filed notes
("what actions are due today?", "list my recent media saves"). Sending the
full body of every matching note to Gemini would quickly exhaust the context
window, increase latency, and raise API costs — especially for broad queries
that match dozens of files.

## Decision

For the default and metadata query modes, send only filenames and YAML
frontmatter to Gemini (not full note bodies). Frontmatter contains title,
dates, tags, status, project, media type, and other structured fields — enough
to answer most questions. A separate `grep` mode sends short context snippets
when the user needs to search within file contents.

## Consequences

- Vault queries stay fast and cheap, even across hundreds of notes.
- Questions about structured metadata ("what's due this week?", "list all
  media by type") work well because the answer is fully contained in
  frontmatter.
- Questions requiring full-text reasoning ("summarise my notes on
  Kubernetes") need the `grep` mode, which is more expensive but
  still bounded by snippet length.
- This design depends on good frontmatter quality — the filing agent must
  produce comprehensive YAML fields for queries to be useful.
