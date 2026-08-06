# Common RSS Feed URL Patterns

Reference guide for common RSS/Atom feed locations across different blogging platforms.

## WordPress
- `/feed/` (most common)
- `/feed`
- `/?feed=rss2`
- `/rss/`

## Ghost
- `/rss/` (default)
- `/feed/`

## Bearblog
- `/feed/` (always at root)
- Format: `https://username.bearblog.dev/feed/`

## Substack
- `/feed` (at root)
- Format: `https://username.substack.com/feed`

## Medium
- `/feed` (at user profile)
- Format: `https://medium.com/@username/feed`

## Blogger (Blogspot)
- `/feeds/posts/default`
- `/feeds/posts/default?alt=rss`

## Hugo
- `/index.xml` (default)
- `/feed.xml`

## Jekyll
- `/feed.xml` (default)

## Tumblr
- `/rss`

## Common Patterns to Try
1. `{blog_url}/feed/`
2. `{blog_url}/feed`
3. `{blog_url}/rss/`
4. `{blog_url}/atom.xml`
5. `{blog_url}/feed.xml`
6. `{blog_url}/index.xml`

## HTML Detection
Look for `<link>` tags in HTML `<head>`:
```html
<link rel="alternate" type="application/rss+xml" href="/feed/" />
<link rel="alternate" type="application/atom+xml" href="/atom.xml" />
```
