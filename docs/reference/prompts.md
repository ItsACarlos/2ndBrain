# AI Prompts Reference

All Gemini AI prompts used by 2ndBrain are stored as standalone Markdown
files. This page links each prompt with a description of when and how it
is used.

## Agent Prompts

These prompts are used during normal Slack message processing.

### Router Prompt

Classifies incoming messages by intent and dispatches to the correct agent.
Built dynamically with registered agent descriptions, current time, and
active directives.

```{literalinclude} ../../src/brain/agents/router_prompt.md
:language: markdown
```

### Filing Prompt

Instructs Gemini to classify content and produce structured JSON with
folder, slug, and full Markdown note content including YAML frontmatter.

```{literalinclude} ../../src/brain/prompt.md
:language: markdown
```

### Vault Query Prompt

System instructions for answering questions about vault content. The
`{current_time}` and `{data_description}` placeholders are filled at
runtime depending on the query mode (default, metadata, or grep).

```{literalinclude} ../../src/brain/agents/vault_query_prompt.md
:language: markdown
```

### Vault Edit Planner Prompt

Plans frontmatter edits across one or many vault notes. Gemini receives
candidate files and returns a structured JSON edit plan. The
`{current_time}` placeholder is filled at runtime.

```{literalinclude} ../../src/brain/agents/vault_edit_prompt.md
:language: markdown
```

## Migration Prompts

These prompts are used by the vault migration tooling, not during normal
Slack operation.

### Reclassify Prompt

Reviews existing notes and suggests metadata improvements — category
changes, better tags, or missing frontmatter fields. The `{frontmatter}`
and `{body}` placeholders are filled per-file.

```{literalinclude} ../../src/brain/reclassify_prompt.md
:language: markdown
```

### Vault Migration Prompt

Used by the standalone migration script to convert notes from an old
Obsidian vault into the new vault's structure and frontmatter schema.

```{literalinclude} ../../scripts/migrate_old_vault/migrate_prompt.md
:language: markdown
```
