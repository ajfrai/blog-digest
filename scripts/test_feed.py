#!/usr/bin/env python3
"""
Test if an RSS/Atom feed URL is valid and can be parsed with feedparser.
Returns JSON with test results.
"""

import sys
import json
import feedparser
import requests
from datetime import datetime


def test_feed(feed_url, timeout=10):
    """
    Test if a feed URL is valid and working.

    Returns:
        dict: Test results with 'valid', 'title', 'entries', 'latest_entry', 'error' keys
    """
    result = {
        'valid': False,
        'url': feed_url,
        'title': None,
        'entries': 0,
        'latest_entry': None,
        'error': None
    }

    try:
        # Fetch feed
        response = requests.get(feed_url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; FeedTester/1.0)'
        })

        if response.status_code != 200:
            result['error'] = f"HTTP {response.status_code}"
            return result

        # Parse with feedparser
        feed = feedparser.parse(response.content)

        # Check for parsing errors
        if feed.bozo:
            result['error'] = f"Parse error: {feed.bozo_exception}"
            return result

        # Check if feed has entries
        if len(feed.entries) == 0:
            result['error'] = "No entries found in feed"
            return result

        # Feed is valid
        result['valid'] = True
        result['title'] = feed.feed.get('title', 'Untitled Feed')
        result['entries'] = len(feed.entries)

        # Get latest entry info
        if feed.entries:
            latest = feed.entries[0]
            result['latest_entry'] = {
                'title': latest.get('title', 'Untitled'),
                'link': latest.get('link', ''),
                'published': latest.get('published', latest.get('updated', ''))
            }

        return result

    except requests.RequestException as e:
        result['error'] = f"Network error: {str(e)}"
        return result
    except Exception as e:
        result['error'] = f"Unexpected error: {str(e)}"
        return result


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: test_feed.py <feed_url>")
        sys.exit(1)

    feed_url = sys.argv[1]
    result = test_feed(feed_url)

    print(json.dumps(result, indent=2))

    # Exit with error code if invalid
    sys.exit(0 if result['valid'] else 1)
