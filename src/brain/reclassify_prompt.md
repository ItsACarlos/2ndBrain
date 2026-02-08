You are reviewing an existing Obsidian vault note. Given its current YAML
frontmatter and body, return a JSON object with corrected/improved values.

ONLY return fields that should CHANGE. Do not include fields that are already
correct. If nothing needs changing, return an empty JSON object {{}}.

Possible changes:
- category: move to a better folder (Projects/Actions/Media/Reference/Memories/Inbox)
- tags: improved/expanded tag list (YAML list of strings)
- Any category-specific field (see the schema below)

Category field schemas:
- Projects: project_name, priority (1 - Urgent / 2 - High / 3 - Medium / 4 - Low)
- Actions: action_item, due_date, project (wiki-link), status, priority
- Media: media_title, media_type (book/film/tv/podcast/article/video), creator,
  url, status
- Reference: topic, related_projects (list of wiki-links)
- Memories: people (list of names), location, memory_date

Return ONLY raw JSON — no markdown fences, no explanation.

## Current frontmatter
{frontmatter}

## Note body (first 500 chars)
{body}
