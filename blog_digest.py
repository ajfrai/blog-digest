#!/usr/bin/env python3
"""
Daily Blog Digest - Fetches articles from AI research blogs and sends email digest
"""

import feedparser
import json
import os
import argparse
import requests
import hashlib
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import time

import mailer

# Configuration
_email_to_raw = os.getenv("EMAIL_TO", "")
EMAIL_RECIPIENTS = [e.strip() for e in _email_to_raw.split(",") if e.strip()]
ARTICLES_PER_DAY = 10
MIN_PER_SOURCE = 1  # Guarantee at least 1 article per source
MAX_PER_SOURCE = 2  # Maximum articles per source
STATE_FILE = Path.home() / "blog_digest" / ".blog_digest_state.json"

# Priority sources (processed first)
PRIORITY_SOURCES = {
    "Anthropic Research",
    "Anthropic Engineering",
    "Anthropic News",
    "Google DeepMind",
    "Google Research"
}

# Blog RSS feeds - Research focused
BLOGS = {
    "Anthropic Research": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml",
    "Anthropic Engineering": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
    "Anthropic News": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
    "Armin Ronacher": "https://lucumr.pocoo.org/feed",
    "Sankalp": "https://sankalp.bearblog.dev/feed/",
    "OpenAI": "https://openai.com/news/rss.xml",  # Mix of technical and product posts
    "Cursor": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_cursor.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Google Research": "https://blog.research.google/feeds/posts/default",
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "Ethan Mollick": "https://www.oneusefulthing.org/feed",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Alexis Gallagher": "https://alexisgallagher.com/rss",
    "Andrey Karpathy": "https://karpathy.bearblog.dev/feed/",
    "BAIR Blog": "https://bair.berkeley.edu/blog/feed.xml",
    "Chip Huyen": "https://huyenchip.com/feed.xml",
    "Christopher Olah": "http://colah.github.io/rss.xml",
    "Eugene Yan": "https://eugeneyan.com/rss/",
    "Hamel Husain": "https://hamelhusain.substack.com/feed",
    "Jay Alammar": "https://jalammar.github.io/feed.xml",
    "Lilian Weng": "https://lilianweng.github.io/index.xml",
    "Mario Zechner": "https://mariozechner.at/rss.xml",
    "Martin Gratzer": "https://mgratzer.com/rss",
    "Nathan Lambert": "https://www.interconnects.ai/feed",
    "Sebastian Raschka": "https://sebastianraschka.com/rss_feed.xml",
    "Vicki Boykis": "https://veekaybee.github.io/index.xml",
    "fast.ai": "https://www.fast.ai/index.xml",
}

# Email configuration - UPDATE THESE
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "your-email@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your-app-password")

# Cloudflare Worker URL for tracking (set via environment variable)
WORKER_URL = os.getenv("WORKER_URL", "")


def load_state():
    """Load state from both local file and Cloudflare Worker KV"""
    local_state = {"sent_articles": [], "clicked": [], "downvoted": []}

    # Load local state
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            local_state = json.load(f)

    # Ensure all required keys exist
    if "clicked" not in local_state:
        local_state["clicked"] = []
    if "downvoted" not in local_state:
        local_state["downvoted"] = []

    # Fetch state from Worker KV if configured
    if WORKER_URL:
        try:
            response = requests.get(f"{WORKER_URL}/api/state", timeout=10)
            if response.status_code == 200:
                remote_state = response.json()
                # Merge remote state with local state
                local_state["clicked"] = list(set(local_state["clicked"] + remote_state.get("clicked", [])))
                local_state["downvoted"] = list(set(local_state["downvoted"] + remote_state.get("downvoted", [])))
                print(f"Synced state from Worker: {len(remote_state.get('clicked', []))} clicked, {len(remote_state.get('downvoted', []))} downvoted")
        except Exception as e:
            print(f"Warning: Could not fetch state from Worker: {e}")

        try:
            response = requests.get(f"{WORKER_URL}/api/unsubscribed", timeout=10)
            if response.status_code == 200:
                local_state["unsubscribed"] = response.json()
                print(f"Unsubscribed emails: {local_state['unsubscribed']}")
        except Exception as e:
            print(f"Warning: Could not fetch unsubscribed list from Worker: {e}")

    return local_state


def save_state(state):
    """Save sent article IDs"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def is_article_recent(article, max_age_days=7):
    """Check if article is within max_age_days"""
    # Try published_parsed first, then updated_parsed
    published_time = article.get('published_parsed') or article.get('updated_parsed')

    if not published_time:
        return False  # Exclude if no date available

    try:
        published_dt = datetime(*published_time[:6])
        cutoff_date = datetime.now() - timedelta(days=max_age_days)
        return published_dt >= cutoff_date
    except Exception:
        return False  # Exclude if parsing fails


STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "how", "why", "what",
    "this", "that", "it", "its", "from", "as", "be", "has", "have", "had",
    "not", "no", "do", "can", "will", "we", "our", "your", "my", "their",
    "new", "using", "new", "about", "more", "when", "up", "into",
}


def _title_words(title):
    """Extract meaningful lowercase words from a title."""
    return [
        w.strip("\"'.,!?:;()[]{}").lower()
        for w in title.split()
        if len(w) > 2 and w.lower().strip("\"'.,!?:;()[]{}") not in STOP_WORDS
    ]


def compute_ranker_features(state):
    """
    Build scoring features from historical click/downvote signals.

    Returns:
        source_stats: {source: {shown, clicked, downvoted}}
        liked_words:  Counter of words from clicked article titles
        disliked_words: Counter of words from downvoted article titles
    """
    metadata = state.get("article_metadata", {})
    clicked_ids = set(state.get("clicked", []))
    downvoted_ids = set(state.get("downvoted", []))

    source_stats = {}
    liked_words = Counter()
    disliked_words = Counter()

    for art_id, meta in metadata.items():
        src = meta.get("source", "")
        if src not in source_stats:
            source_stats[src] = {"shown": 0, "clicked": 0, "downvoted": 0}
        source_stats[src]["shown"] += 1

        words = _title_words(meta.get("title", ""))
        if art_id in clicked_ids:
            source_stats[src]["clicked"] += 1
            liked_words.update(words)
        if art_id in downvoted_ids:
            source_stats[src]["downvoted"] += 1
            disliked_words.update(words)

    return source_stats, liked_words, disliked_words


def score_article(article, source_stats, liked_words, disliked_words):
    """
    Score an article in [-1, 1] range based on:
      - Source affinity (CTR signal per source)
      - Keyword affinity (title word overlap with liked vs disliked)

    Higher = more likely to be clicked by the user.
    """
    src = article["source"]
    stats = source_stats.get(src, {})
    n_shown = stats.get("shown", 0)

    # --- Source affinity ---
    if n_shown >= 3:
        # (clicks - downvotes) / shown, scaled to [-1, 1]
        source_score = (stats["clicked"] - stats["downvoted"]) / n_shown
    else:
        source_score = 0.0  # not enough data yet

    # --- Keyword affinity ---
    words = _title_words(article.get("title", ""))
    total_liked = sum(liked_words.values()) or 1
    total_disliked = sum(disliked_words.values()) or 1
    n_signals = total_liked + total_disliked

    if words and n_signals > 10:
        pos = sum(liked_words.get(w, 0) for w in words) / total_liked
        neg = sum(disliked_words.get(w, 0) for w in words) / total_disliked
        keyword_score = pos - neg
        # Normalize: keyword_score is in a small range, scale it
        keyword_score = max(-1.0, min(1.0, keyword_score * 20))
    else:
        keyword_score = 0.0

    # Blend: give more weight to source when we have data, else lean on keywords
    source_weight = min(0.6, 0.1 * (n_shown / 3)) if n_shown >= 3 else 0.3
    keyword_weight = 1.0 - source_weight

    return source_weight * source_score + keyword_weight * keyword_score


def fetch_articles():
    """Fetch articles from all blogs"""
    all_articles = []

    for blog_name, feed_url in BLOGS.items():
        try:
            print(f"Fetching from {blog_name}...")
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:10]:  # Get latest 10 from each
                article = {
                    "title": entry.get("title", "No title"),
                    "link": entry.get("link", ""),
                    "source": blog_name,
                    "published": entry.get("published", entry.get("updated", "")),
                    "published_parsed": entry.get("published_parsed", entry.get("updated_parsed")),
                    "id": entry.get("id", entry.get("link", ""))
                }
                all_articles.append(article)
        except Exception as e:
            print(f"Error fetching {blog_name}: {e}")

    # Sort by published date (newest first)
    all_articles.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_articles


def _select_by_date(candidates):
    """Original date-based selection with source diversity."""
    by_source = {}
    for a in candidates:
        by_source.setdefault(a["source"], []).append(a)

    priority = {s: v for s, v in by_source.items() if s in PRIORITY_SOURCES}
    other = {s: v for s, v in by_source.items() if s not in PRIORITY_SOURCES}

    selected = []
    for arts in priority.values():
        selected.extend(arts[:MAX_PER_SOURCE])
    for arts in other.values():
        selected.extend(arts[:MAX_PER_SOURCE])

    selected.sort(key=lambda x: x.get("published", ""), reverse=True)
    return selected[:ARTICLES_PER_DAY]


def _select_by_rank(candidates, source_stats, liked_words, disliked_words):
    """Ranked selection with source diversity cap."""
    for a in candidates:
        a["_score"] = score_article(a, source_stats, liked_words, disliked_words)

    candidates.sort(key=lambda x: (x["_score"], x.get("published", "")), reverse=True)

    selected = []
    source_counts = {}
    for article in candidates:
        src = article["source"]
        if source_counts.get(src, 0) < MAX_PER_SOURCE:
            selected.append(article)
            source_counts[src] = source_counts.get(src, 0) + 1
        if len(selected) >= ARTICLES_PER_DAY:
            break
    return selected


def get_new_articles(articles, state, max_age_days=7):
    """
    Filter articles and select for the digest.

    When RANKER_SHADOW=true (default), the ranker runs in shadow mode:
    scores are logged but the original date-based selection is used.

    Set RANKER_LIVE=true to promote the ranker to production.
    """
    excluded_ids = set(state.get("clicked", [])) | set(state.get("downvoted", []))

    candidates = [
        a for a in articles
        if a["id"] not in excluded_ids and is_article_recent(a, max_age_days)
    ]

    # Always compute ranker features for logging / data collection
    source_stats, liked_words, disliked_words = compute_ranker_features(state)
    n_signals = len(state.get("article_metadata", {}))

    ranker_live = os.getenv("RANKER_LIVE", "").lower() in ("1", "true", "yes")

    if n_signals > 0 or ranker_live:
        ranked = _select_by_rank(
            [dict(a) for a in candidates],  # shallow copy to avoid mutating originals
            source_stats, liked_words, disliked_words
        )
        ranked_ids = [a["id"] for a in ranked]

        if ranker_live:
            print(f"[ranker] LIVE — {n_signals} labeled articles, "
                  f"{len(state.get('clicked',[]))} clicks / {len(state.get('downvoted',[]))} downvotes")
            for i, a in enumerate(ranked, 1):
                print(f"  [{i:2d}] score={a.get('_score', 0):.3f}  {a['source']}: {a['title'][:60]}")
            return ranked

        # Shadow mode: log what the ranker would pick vs what we actually send
        date_selected = _select_by_date(candidates)
        date_ids = [a["id"] for a in date_selected]

        would_add = [a for a in ranked if a["id"] not in date_ids]
        would_drop = [a for a in date_selected if a["id"] not in ranked_ids]

        print(f"[ranker:shadow] {n_signals} labeled articles, "
              f"{len(state.get('clicked',[]))} clicks / {len(state.get('downvoted',[]))} downvotes")
        print("[ranker:shadow] Ranked order (not used for sending):")
        for i, a in enumerate(ranked, 1):
            marker = "+" if a["id"] not in date_ids else " "
            print(f"  [{i:2d}]{marker} score={a.get('_score', 0):.3f}  {a['source']}: {a['title'][:60]}")
        if would_add:
            print("[ranker:shadow] Would ADD vs date-sort:")
            for a in would_add:
                print(f"    + {a['source']}: {a['title'][:60]}")
        if would_drop:
            print("[ranker:shadow] Would DROP vs date-sort:")
            for a in would_drop:
                print(f"    - {a['source']}: {a['title'][:60]}")

        return date_selected

    # No signals yet — fall back to date-based selection silently
    return _select_by_date(candidates)


def create_email_body(articles, recipient_email):
    """Create HTML email body with tracking links"""
    html = """
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            h1 {{ color: #2c3e50; }}
            .article {{ margin: 20px 0; padding: 15px; background: #f8f9fa; border-left: 4px solid #3498db; }}
            .article h2 {{ margin-top: 0; color: #2980b9; }}
            .source {{ color: #7f8c8d; font-size: 0.9em; }}
            .actions {{ margin-top: 10px; }}
            a {{ color: #3498db; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .downvote {{ color: #e74c3c; font-size: 0.9em; margin-left: 15px; }}
            .footer {{ margin-top: 40px; padding-top: 15px; border-top: 1px solid #ddd; font-size: 0.8em; color: #999; text-align: center; }}
            .footer a {{ color: #999; }}
        </style>
    </head>
    <body>
        <h1>Your Daily AI Blog Digest</h1>
        <p>Here are your {count} articles for {date}:</p>
    """.format(count=len(articles), date=datetime.now().strftime("%B %d, %Y"))

    for i, article in enumerate(articles, 1):
        # Create tracking link if Worker URL is configured
        if WORKER_URL:
            article_link = f"{WORKER_URL}/track?id={quote(article['id'])}&url={quote(article['link'])}"
            downvote_link = f"{WORKER_URL}/downvote?id={quote(article['id'])}"
        else:
            # Fallback to direct link if no Worker configured
            article_link = article['link']
            downvote_link = None

        html += f"""
        <div class="article">
            <h2>{i}. {article['title']}</h2>
            <p class="source">Source: {article['source']}</p>
            <div class="actions">
                <a href="{article_link}">Read article →</a>
        """

        if downvote_link:
            html += f'<a href="{downvote_link}" class="downvote">👎 Not interested</a>'

        html += """
            </div>
        </div>
        """

    if WORKER_URL:
        unsubscribe_link = f"{WORKER_URL}/unsubscribe?email={quote(recipient_email)}"
        html += f"""
        <div class="footer">
            <p>You're receiving this because you subscribed to the AI Blog Digest.<br>
            <a href="{unsubscribe_link}">Unsubscribe</a></p>
        </div>
        """

    html += """
    </body>
    </html>
    """
    return html


def send_email(articles, unsubscribed=None, recipients_override=None):
    """Send individual emails to each recipient, skipping unsubscribed addresses"""
    if not articles:
        print("No new articles to send")
        return False

    if unsubscribed is None:
        unsubscribed = []

    recipients = recipients_override if recipients_override is not None else EMAIL_RECIPIENTS
    active_recipients = [r for r in recipients if r not in unsubscribed]
    if not active_recipients:
        print("No active recipients to send to")
        return False

    # Build plain text body once (same for all recipients)
    text_body = f"Your Daily AI Blog Digest - {datetime.now().strftime('%B %d, %Y')}\n\n"
    for i, article in enumerate(articles, 1):
        if WORKER_URL:
            article_link = f"{WORKER_URL}/track?id={quote(article['id'])}&url={quote(article['link'])}"
            downvote_link = f"{WORKER_URL}/downvote?id={quote(article['id'])}"
        else:
            article_link = article['link']
            downvote_link = None

        text_body += f"{i}. {article['title']}\n"
        text_body += f"   Source: {article['source']}\n"
        text_body += f"   Link: {article_link}\n"
        if downvote_link:
            text_body += f"   Not interested: {downvote_link}\n"
        text_body += "\n"

    subject = f"Daily AI Blog Digest - {datetime.now().strftime('%b %d, %Y')}"
    config = mailer.SMTPConfig(SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD)

    messages = []
    for recipient in active_recipients:
        extra_headers = {}
        plain_with_unsub = text_body
        if WORKER_URL:
            unsub_link = f"{WORKER_URL}/unsubscribe?email={quote(recipient)}"
            extra_headers['List-Unsubscribe'] = f"<{unsub_link}>"
            extra_headers['List-Unsubscribe-Post'] = "List-Unsubscribe=One-Click"
            plain_with_unsub += f"\nUnsubscribe: {unsub_link}\n"

        messages.append(mailer.build_message(
            subject=subject,
            sender=SMTP_USER,
            recipient=recipient,
            text=plain_with_unsub,
            html=create_email_body(articles, recipient),
            extra_headers=extra_headers,
        ))

    try:
        mailer.send_messages(messages, config=config)
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

    for recipient in active_recipients:
        print(f"Email sent to {recipient} with {len(articles)} articles")
    return True


def main():
    parser = argparse.ArgumentParser(description='Daily Blog Digest - Fetches articles from AI research blogs and sends email digest')
    parser.add_argument('--max-age-days', type=int, default=7,
                        help='Maximum age of articles in days (default: 7)')
    parser.add_argument('--test', action='store_true',
                        help='Send a test email without updating state')
    args = parser.parse_args()

    print(f"Running blog digest at {datetime.now()}")
    print(f"Max article age: {args.max_age_days} days")
    print(f"Recipients: {EMAIL_RECIPIENTS}")

    # Load state
    state = load_state()
    unsubscribed = state.get("unsubscribed", [])
    if unsubscribed:
        print(f"Skipping unsubscribed: {unsubscribed}")

    # Fetch articles
    all_articles = fetch_articles()
    print(f"Fetched {len(all_articles)} total articles")

    new_articles = get_new_articles(all_articles, state, args.max_age_days)

    if args.test:
        print(f"TEST MODE: sending {len(new_articles)} articles to {SMTP_USER} only (state not saved)")
    else:
        print(f"Found {len(new_articles)} new articles")

    if new_articles:
        # Persist article metadata before sending so future runs can use click/downvote signals
        if not args.test:
            if "article_metadata" not in state:
                state["article_metadata"] = {}
            for article in new_articles:
                state["article_metadata"][article["id"]] = {
                    "title": article["title"],
                    "source": article["source"],
                }

        recipients_override = [SMTP_USER] if args.test else None
        if send_email(new_articles, unsubscribed=unsubscribed, recipients_override=recipients_override):
            if not args.test:
                save_state(state)
    else:
        print("No new articles found")


if __name__ == "__main__":
    main()
