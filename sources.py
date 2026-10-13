#!/usr/bin/env python3
"""
Candidate gathering for the AI Digest issue builder.

Pulls raw material from four kinds of source and returns flat lists of
candidates. Nothing here calls a model; build_issue.py decides what to keep.
"""

import calendar
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import quote_plus

import feedparser
import requests

from blog_digest import BLOGS

USER_AGENT = "Mozilla/5.0 (compatible; ai-digest/2.0)"
TIMEOUT = 25

# General AI news. Google News queries widen the net beyond the tech press.
NEWS_FEEDS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat": "https://venturebeat.com/category/ai/feed/",
    "Ars Technica": "https://arstechnica.com/ai/feed/",
    "MIT Technology Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "The Register": "https://www.theregister.com/software/ai_ml/headlines.atom",
    "Hacker News": "https://hnrss.org/newest?q=AI+OR+LLM+OR+OpenAI+OR+Anthropic&points=150",
    "Google News: AI business": "https://news.google.com/rss/search?q="
        + quote_plus('("artificial intelligence" OR AI) (funding OR acquisition OR revenue OR earnings OR valuation OR deal) when:2d')
        + "&hl=en-US&gl=US&ceid=US:en",
    "Google News: AI labs": "https://news.google.com/rss/search?q="
        + quote_plus("(OpenAI OR Anthropic OR DeepMind OR Nvidia OR Mistral OR xAI OR Meta AI) when:2d")
        + "&hl=en-US&gl=US&ceid=US:en",
    "Google News: AI research": "https://news.google.com/rss/search?q="
        + quote_plus('AI (breakthrough OR "new model" OR benchmark OR researchers) when:2d')
        + "&hl=en-US&gl=US&ceid=US:en",
}

# Repositories whose releases are worth watching for demo-able features.
REPOS = [
    "anthropics/claude-code", "anthropics/anthropic-sdk-python", "openai/codex", "openai/openai-agents-python",
    "modelcontextprotocol/python-sdk", "modelcontextprotocol/typescript-sdk", "langchain-ai/langgraph",
    "langchain-ai/langchain", "run-llama/llama_index", "pydantic/pydantic-ai", "stanfordnlp/dspy",
    "huggingface/transformers", "huggingface/smolagents", "huggingface/diffusers", "vllm-project/vllm",
    "ollama/ollama", "ggml-org/llama.cpp", "ml-explore/mlx", "unslothai/unsloth", "BerriAI/litellm",
    "simonw/llm", "vercel/ai", "microsoft/autogen", "crewAIInc/crewAI", "open-webui/open-webui",
    "comfyanonymous/ComfyUI", "chroma-core/chroma", "qdrant/qdrant", "lancedb/lancedb", "browser-use/browser-use",
]

ARXIV_URL = ("http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL"
             "&sortBy=submittedDate&sortOrder=descending&max_results=120")
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "pre", "tr", "blockquote", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.depth = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_to_text(html):
    """Strip markup down to readable text."""
    parser = _TextExtractor()
    try:
        parser.feed(html or "")
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch_page_text(url, limit):
    """Fetch a page and return (text, truncated). Empty text on any failure."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "html"):
            return "", False
        text = html_to_text(resp.text)
    except Exception:
        return "", False
    return text[:limit], len(text) > limit


def _parse(url):
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _age_hours(entry):
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return None
    return (time.time() - calendar.timegm(stamp)) / 3600


def _entries(kind, source, url, max_age_hours, per_feed, snippet_len=400):
    out = []
    try:
        feed = _parse(url)
    except Exception as e:
        print(f"  ! {source}: {e}")
        return out
    for entry in feed.entries[:per_feed]:
        age = _age_hours(entry)
        if age is None or age > max_age_hours or not entry.get("link"):
            continue
        body = entry.get("summary", "")
        if entry.get("content"):
            body = entry["content"][0].get("value", body)
        out.append({
            "kind": kind,
            "source": source,
            "title": html_to_text(entry.get("title", "")).strip(),
            "url": entry["link"],
            "age_hours": round(age),
            "snippet": html_to_text(body)[:snippet_len],
            "feed_text": html_to_text(body),
        })
    return out


def _gather(jobs):
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = pool.map(lambda job: job[0](*job[1:]), jobs)
    return [item for batch in results for item in batch]


def fetch_news(max_age_hours=40):
    return _gather([(_entries, "news", name, url, max_age_hours, 40) for name, url in NEWS_FEEDS.items()])


def fetch_blogs(max_age_hours=96):
    return _gather([(_entries, "blog", name, url, max_age_hours, 8) for name, url in BLOGS.items()])


def fetch_repos(max_age_hours=168):
    jobs = [(_entries, "repo", repo, f"https://github.com/{repo}/releases.atom", max_age_hours, 4, 900) for repo in REPOS]
    releases = _gather(jobs)
    for release in releases:
        # Release titles are usually a bare version number; name the repository too.
        release["title"] = f"{release['source']} {release['title']}"
    return releases


def _arxiv_id(url):
    match = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", url or "")
    return match.group(1) if match else None


def fetch_papers():
    """New preprints plus older ones that are gaining attention right now.

    Popularity signals: Hugging Face's trending list and its top papers of the
    week and month, and arXiv links doing well on Hacker News. Each candidate's
    source line lists the signals that apply so the editor can weigh them.
    """
    papers = {}

    def add(pid, title, abstract, published, signal):
        paper = papers.setdefault(pid, {"title": "", "abstract": "", "published": "", "signals": []})
        paper["title"] = paper["title"] or " ".join((title or "").split())
        paper["abstract"] = paper["abstract"] or " ".join((abstract or "").split())
        paper["published"] = paper["published"] or (published or "")[:10]
        if signal and signal.endswith("upvotes on Hugging Face"):
            # The same paper shows up in several lists with slightly different counts; keep the highest.
            paper["upvotes"] = max(paper.get("upvotes", 0), int(signal.split()[0]))
        elif signal and signal not in paper["signals"]:
            paper["signals"].append(signal)

    today = datetime.now()
    last_week = today - timedelta(days=7)
    hf_queries = [
        ({"limit": 60}, None),
        ({"limit": 30, "sort": "trending"}, "trending on Hugging Face"),
        ({"limit": 20, "week": "{}-W{:02d}".format(*today.isocalendar()[:2])}, "among this week's most upvoted"),
        ({"limit": 20, "week": "{}-W{:02d}".format(*last_week.isocalendar()[:2])}, "among last week's most upvoted"),
        ({"limit": 15, "month": today.strftime("%Y-%m")}, "among this month's most upvoted"),
    ]
    for params, signal in hf_queries:
        try:
            resp = requests.get(HF_PAPERS_URL, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            for row in resp.json():
                paper = row.get("paper", {})
                if not paper.get("id"):
                    continue
                add(paper["id"], paper.get("title"), paper.get("summary"), paper.get("publishedAt"),
                    f"{paper.get('upvotes', 0)} upvotes on Hugging Face")
                if signal:
                    add(paper["id"], None, None, None, signal)
        except Exception as e:
            print(f"  ! Hugging Face papers {params}: {e}")

    try:
        since = int(time.time()) - 14 * 86400
        resp = requests.get(HN_SEARCH_URL, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, params={
            "query": "arxiv.org", "restrictSearchableAttributes": "url", "tags": "story",
            "numericFilters": f"points>40,created_at_i>{since}", "hitsPerPage": 40})
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            pid = _arxiv_id(hit.get("url"))
            if pid:
                add(pid, None, None, None, f"{hit['points']} points on Hacker News")
    except Exception as e:
        print(f"  ! Hacker News papers: {e}")

    # Fill in titles and abstracts for papers known only by id, and add the newest listings.
    missing = [pid for pid, paper in papers.items() if not paper["abstract"]]
    queries = [ARXIV_URL]
    if missing:
        queries.append("http://export.arxiv.org/api/query?max_results=60&id_list=" + ",".join(missing))
    for url in queries:
        try:
            for entry in _parse(url).entries:
                pid = _arxiv_id(entry.get("id", "").replace("http://", "https://"))
                if pid:
                    add(pid, entry.get("title"), entry.get("summary"), entry.get("published"), None)
        except Exception as e:
            print(f"  ! arXiv: {e}")

    out = []
    for pid, paper in papers.items():
        if not paper["title"]:
            continue
        source = "arXiv" + (f", published {paper['published']}" if paper["published"] else "")
        signals = ([f"{paper['upvotes']} upvotes on Hugging Face"] if paper.get("upvotes") else []) + paper["signals"]
        if signals:
            source += "; " + "; ".join(signals)
        out.append({"kind": "paper", "source": source, "title": paper["title"], "url": f"https://arxiv.org/abs/{pid}",
                    "age_hours": None, "snippet": paper["abstract"][:500], "feed_text": paper["abstract"]})
    return out


def fetch_all(exclude_urls=()):
    """Return every candidate, each with a short id, minus anything already used."""
    exclude = set(exclude_urls)
    groups = [("n", fetch_news()), ("b", fetch_blogs()), ("p", fetch_papers()), ("r", fetch_repos())]
    candidates, seen = [], set()
    for prefix, items in groups:
        n = 0
        for item in items:
            if item["url"] in exclude or item["url"] in seen or not item["title"]:
                continue
            seen.add(item["url"])
            n += 1
            item["id"] = f"{prefix}{n}"
            candidates.append(item)
        print(f"  {n} candidates of kind {prefix}")
    return candidates


if __name__ == "__main__":
    for c in fetch_all():
        print(c["id"], "|", c["source"], "|", c["title"][:90])
