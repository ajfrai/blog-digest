---
name: add-blog
description: Add new blogs to the blog_digest system. Use when the user wants to add a blog, RSS feed, or new source to their blog digest. Supports automatic RSS/Atom feed discovery for WordPress, Ghost, Bearblog, Substack, Medium, and other platforms. Trigger on requests like "add this blog", "add https://example.com to my digest", or "subscribe to this blog".
---

# Add Blog to Blog Digest

Add new blogs to the blog_digest monitoring system with automatic RSS feed discovery.

## Workflow

### 1. Discover RSS Feed

Run `scripts/discover_feed.py` with the blog URL:

```bash
python3 scripts/discover_feed.py <blog_url>
```

This returns JSON with:
- `blog_title`: Suggested friendly name from the blog
- `feeds`: Array of discovered feeds with `url`, `title`, `type`, `entries`

If multiple feeds are found, prefer:
1. Main site feed over category-specific feeds
2. RSS over Atom (for consistency with existing feeds)
3. Feeds with more entries

### 2. Validate Feed

Test the selected feed URL:

```bash
python3 scripts/test_feed.py <feed_url>
```

Returns test results including:
- `valid`: Boolean indicating if feed works
- `entries`: Number of articles in feed
- `latest_entry`: Most recent article info
- `error`: Any error message if invalid

### 3. Get Friendly Name

Present the suggested blog title from step 1 and ask the user to confirm or provide an alternative name.

Use AskUserQuestion with:
- Pre-filled option with suggested name (marked as Recommended)
- "Other" option for custom name

### 4. Add to BLOGS Dictionary

Read `/home/abraham/blog_digest/blog_digest.py` and locate the BLOGS dictionary (around line 37-49).

Add the new blog entry in alphabetical order by friendly name:

```python
BLOGS = {
    "Anthropic Research": "https://...",
    "New Blog Name": "https://newblog.com/feed/",  # New entry
    "OpenAI": "https://...",
}
```

Use the Edit tool to add the entry, preserving exact formatting and indentation.

### 5. Verify Addition

After editing:
1. Read the file again to confirm the change
2. Report success with: blog name, feed URL, and number of recent articles found

## Example Usage

User: "Add https://sankalp.bearblog.dev/"

Steps:
1. Discover feed → finds `https://sankalp.bearblog.dev/feed/`
2. Test feed → valid, 15 entries
3. Suggest name "Sankalp" (from blog title)
4. User confirms or provides custom name
5. Add to BLOGS dictionary
6. Report success

## Common Feed Patterns

For reference on platform-specific patterns, see [feed-patterns.md](references/feed-patterns.md).

## Error Handling

If feed discovery fails:
1. Check if URL is accessible
2. Try common patterns from references/feed-patterns.md manually
3. Ask user if they know the feed URL
4. Search blog HTML for feed links

If feed validation fails:
1. Report the specific error
2. Try alternative discovered feeds
3. Ask user to verify the blog URL is correct

## Dependencies

Scripts require: `requests`, `trafilatura`, `feedparser`

These are already available in the blog_digest environment.
