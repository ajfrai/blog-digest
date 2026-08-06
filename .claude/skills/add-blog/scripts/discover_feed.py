#!/usr/bin/env python3
"""
Discover RSS/Atom feed URLs from a blog URL.
Returns a list of discovered feeds with metadata.
"""

import sys
import requests
from urllib.parse import urlparse, urljoin
import feedparser
from trafilatura.feeds import find_feed_urls

COMMON_FEED_PATHS = [
    '/feed/', '/feed', '/rss/', '/rss', '/atom.xml',
    '/feed.xml', '/rss.xml', '/index.xml', '/feeds/posts/default',
]


def discover_feeds(blog_url, timeout=10):
    """
    Discover RSS/Atom feeds from a blog URL.
    Uses trafilatura first, falls back to probing common feed paths.

    Returns:
        dict: {'blog_title': str, 'feeds': list of feed info dicts}
    """
    feeds = []
    seen = set()

    # 1. Use trafilatura for HTML-based discovery
    try:
        for url in find_feed_urls(blog_url) or []:
            if url not in seen:
                seen.add(url)
                info = get_feed_info(url, timeout)
                if info:
                    feeds.append(info)
    except Exception as e:
        print(f"trafilatura: {e}", file=sys.stderr)

    # 2. Fallback: probe common feed paths
    if not feeds:
        for path in COMMON_FEED_PATHS:
            url = urljoin(blog_url, path)
            if url not in seen:
                seen.add(url)
                info = get_feed_info(url, timeout)
                if info:
                    feeds.append(info)
                    break  # stop after first valid feed

    blog_title = feeds[0]['blog_title'] if feeds else extract_domain(blog_url)
    return {'blog_title': blog_title, 'feeds': feeds}


def get_feed_info(feed_url, timeout=10):
    """Get feed metadata."""
    try:
        response = requests.get(feed_url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; FeedDiscovery/1.0)'
        })
        if response.status_code != 200:
            return None

        feed = feedparser.parse(response.content)
        if feed.bozo != 0 or len(feed.entries) == 0:
            return None

        feed_type = 'RSS' if 'rss' in feed_url.lower() else 'Atom'
        if hasattr(feed, 'version'):
            if 'atom' in feed.version.lower():
                feed_type = 'Atom'
            elif 'rss' in feed.version.lower():
                feed_type = 'RSS'

        return {
            'url': feed_url,
            'title': feed.feed.get('title', 'Untitled Feed'),
            'blog_title': feed.feed.get('title', 'Untitled Feed'),
            'type': feed_type,
            'entries': len(feed.entries)
        }

    except Exception as e:
        print(f"Error getting feed info: {e}", file=sys.stderr)
        return None


def extract_domain(url):
    """Extract domain name from URL as fallback title."""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    # Remove www. prefix
    if domain.startswith('www.'):
        domain = domain[4:]
    # Remove TLD
    parts = domain.split('.')
    if len(parts) > 1:
        return parts[0].replace('-', ' ').title()
    return domain.replace('-', ' ').title()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: discover_feed.py <blog_url>")
        sys.exit(1)

    blog_url = sys.argv[1]
    result = discover_feeds(blog_url)

    import json
    print(json.dumps(result, indent=2))
