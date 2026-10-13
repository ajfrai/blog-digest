#!/usr/bin/env python3
"""
AI Digest issue builder.

Gathers candidates, has Claude curate and write the five sections, builds a
demo for each repo feature, renders the static site and optionally records a
podcast, deploys the site and sends the skinny email.

    build_issue.py                       build today's issue into site/
    build_issue.py --deploy              ...and publish it
    build_issue.py --deploy --email all  the full daily run
    build_issue.py --resume              reuse cached stages from an earlier run today
"""

import argparse
import html
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import mailer

# blog_digest reads its settings at import time, so the env file has to be loaded first.
mailer.load_env_file()

import llm
import podcast
import sources
from llm import STR, arr, enum, obj

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
WORK = ROOT / ".work"
STATE_FILE = ROOT / ".digest_state.json"
SUBJECT_MARKER = "[AI Digest]"  # stable prefix so the emails are easy to search for
TEMPLATE = ROOT / "site_template.html"
DEPLOY_SCRIPT = Path.home() / ".claude" / "skills" / "vercel-deploy" / "deploy.sh"
PROJECT_NAME = "ai-digest-daily"

SECTIONS = [
    ("business", "BIZ", "AI business"),
    ("discoveries", "DISC", "AI discoveries"),
    ("blogs", "BLOG", "Blog posts"),
    ("papers", "PPR", "Preprints"),
    ("repos", "REPO", "Repo features"),
]
RATING = {"Strong": 3, "Solid": 2, "Weak": 1, "High": 3, "Medium": 2, "Low": 1}

EDITOR = """You are the editor of AI Digest, a daily newsletter for people who build with and invest in AI. \
Readers are technical and short on time. Write plainly and specifically: concrete numbers, names and consequences, \
no hype, no filler, no hedging boilerplate. Never invent facts, figures or quotes; everything you state must be \
supported by the material you are given. If the material is thin, say less."""


# ---------- stage 1: curate ----------

CURATE_SCHEMA = obj({
    "business": arr(obj({"headline": STR, "ids": arr(STR)})),
    "discoveries": arr(obj({"headline": STR, "ids": arr(STR)})),
    "blogs": arr(STR),
    "papers": arr(STR),
    "repos": arr(STR),
})

CURATE_PROMPT = """Below are today's candidates: news items (ids n*), blog posts (b*), preprints (p*) and \
repository releases (r*). Pick what goes in today's issue.

- business: the 5 to 8 most consequential AI business stories (funding, deals, pricing, earnings, product launches \
with commercial weight, policy that moves money). Group every candidate covering the same story under one entry, \
strongest source first, at most 4 ids.
- discoveries: 5 to 7 technical or scientific advances, deliberately mixed across these lanes: (a) new models and \
capabilities and research results; (b) AI-assisted coding and agent developments (coding agents, new techniques for \
building with them, evals, context and memory methods); (c) libraries, frameworks and packages builders use to make \
products (new releases, new open-source tools, notable techniques and patterns); (d) science and applied results \
(biology, math, robotics, physics, materials). Security, jailbreaks and vulnerabilities are welcome but take at most \
one slot; cover the rest from the other lanes whenever candidates exist. Draw from news, lab blog posts, preprints or \
repository releases. Group ids the same way.
- blogs: 5 to 8 thought pieces from the blog candidates (b*) by individual writers or teams that argue or explain \
something at length. Not product announcements, changelogs, news reports, or link posts that only quote someone \
else. Include pieces you expect to be weak if they are getting attention; readers want to know what to skip.
- papers: 5 to 7 preprints with the clearest path into products or industry practice within about a year. Mix two \
kinds: brand-new preprints, and older ones that are picking up popularity now (their source line says trending, \
most upvoted of the week or month, or gives Hacker News points). Include at least 2 of the second kind whenever \
relevant ones exist; a paper from weeks or months ago is welcome if people are paying attention to it today.
- repos: the 2 to 4 releases whose notes describe a new user-facing feature or capability that could be shown in \
a short demo or lesson. Skip alphas, release candidates and releases that only fix bugs or bump dependencies. One \
release per repository. Developers read this section closely, so return at least 2 whenever any release qualifies.

Do not put the same candidate in two sections. Return only ids that appear below. Fewer good items beat padding.

CANDIDATES
{candidates}"""


def curate(candidates):
    lines = []
    for c in candidates:
        age = f", {c['age_hours']}h ago" if c["age_hours"] is not None else ""
        snippet = c["snippet"][:900 if c["kind"] == "repo" else 300]
        lines.append(f"[{c['id']}] {c['title']} ({c['source']}{age})\n    {snippet}")
    picks = llm.ask_json(EDITOR, CURATE_PROMPT.format(candidates="\n".join(lines)), CURATE_SCHEMA,
                         effort="medium", label="curate")
    known = {c["id"] for c in candidates}
    for key in ("business", "discoveries"):
        for story in picks[key]:
            story["ids"] = [i for i in story["ids"] if i in known][:4]
        picks[key] = [s for s in picks[key] if s["ids"]]
    for key in ("blogs", "papers", "repos"):
        picks[key] = [i for i in picks[key] if i in known]
    return picks


# ---------- stage 2: write ----------

LINK = obj({"label": STR, "url": STR})
WRITE_SCHEMA = obj({
    "subject": STR,
    "lead": STR,
    "business": obj({"brief": STR, "items": arr(obj({"title": STR, "summary": STR, "links": arr(LINK)}))}),
    "discoveries": obj({"brief": STR, "items": arr(obj({"title": STR, "summary": STR, "links": arr(LINK)}))}),
    "blogs": obj({"brief": STR, "items": arr(obj({
        "title": STR, "author": STR, "summary": STR, "verdict": enum("Strong", "Solid", "Weak"),
        "critique": STR, "links": arr(LINK)}))}),
    "papers": obj({"brief": STR, "items": arr(obj({
        "title": STR, "traction": STR, "summary": STR, "potential": enum("High", "Medium", "Low"),
        "rationale": STR, "links": arr(LINK)}))}),
    "repos": obj({"brief": STR, "items": arr(obj({
        "source_id": STR, "repo": STR, "title": STR, "summary": STR, "links": arr(LINK)}))}),
})

WRITE_PROMPT = """Write today's issue ({date}) from the source material below. Items are already chosen and grouped \
by section; write one item per SOURCE GROUP, in order of importance within each section. Drop a group only if its \
material turns out to be empty or off-topic.

Fields:
- subject: an email subject line of at most 70 characters naming the two or three biggest things. No date, no \
"AI Digest" prefix.
- lead: two or three sentences that tell a reader what today adds up to.
- each section's brief: one sentence summarising that section, written to stand alone in an email.
- business and discoveries items: title is a plain declarative headline of at most 90 characters; summary is two or \
three sentences on what happened and why it matters.
- blogs items: title is the post's own title; author is the writer or publication; summary is exactly one sentence \
stating the piece's main claim. verdict and critique are your own critical assessment of quality, judged on the \
text provided: is the argument supported by evidence, is it original, does it survive the obvious objection? \
"Strong" means worth a reader's full attention, "Solid" means correct but skippable, "Weak" means unsupported, \
derivative or mostly promotion. critique is two sentences giving the specific reason. Be willing to say Weak. If \
only an excerpt was available, judge what is there and say so in the critique.
- papers items: title is the paper's title; traction is a short phrase saying why it is here today, built only \
from its source line: "New this week" for a fresh preprint, or the popularity signal for an older one (for example \
"Trending: 341 upvotes on Hugging Face, published 27 Sep" or "177 points on Hacker News, published 2021"); summary is one or two sentences on the result with its headline number \
if the abstract gives one; potential rates how likely this is to reach products or industry practice within a \
year; rationale is one or two sentences on where it would land and what stands in the way.
- repos items: source_id is the id of the release it is based on; repo is "owner/name"; title names the feature in \
plain words (for example "vector-core 0.9 adds hybrid search in one call"); summary is two sentences on what is \
new and who should care.
- links: 1 to 4 per item, each with a short label ("TechCrunch", "Paper", "Release notes", "Read the post") and a \
url copied exactly from the source material. Never write a url that does not appear below.

SOURCE MATERIAL
{material}"""


def _full_text(candidate, limit):
    """Best available text for a candidate: the fetched page, else what the feed carried."""
    if candidate["kind"] in ("paper", "repo"):
        text = candidate["feed_text"]
        return text[:limit], len(text) > limit
    text, truncated = sources.fetch_page_text(candidate["url"], limit)
    if len(text) < 600 and len(candidate["feed_text"]) > len(text):
        text = candidate["feed_text"]
        return text[:limit], len(text) > limit
    return text, truncated


def gather_material(picks, by_id):
    """Fetch the text behind every pick and lay it out as labelled source groups."""
    limits = {"business": 5000, "discoveries": 6000, "blogs": 24000, "papers": 4000, "repos": 9000}
    groups = []
    for key, _, label in SECTIONS:
        for entry in picks[key]:
            ids = entry["ids"] if isinstance(entry, dict) else [entry]
            groups.append((key, label, entry.get("headline", "") if isinstance(entry, dict) else "", ids))

    jobs = [(by_id[i], limits[key] if n == 0 else 1500) for key, _, _, ids in groups for n, i in enumerate(ids)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        texts = dict(zip([c["id"] for c, _ in jobs], pool.map(lambda job: _full_text(*job), jobs)))

    blocks = []
    for key, label, headline, ids in groups:
        block = [f"=== SOURCE GROUP | section: {label}" + (f" | story: {headline}" if headline else "") + " ==="]
        for i in ids:
            c = by_id[i]
            text, truncated = texts[i]
            note = " [excerpt only: the text below is cut short]" if truncated else ""
            block.append(f"[{i}] {c['title']}\nsource: {c['source']}\nurl: {c['url']}{note}\n{text or c['snippet']}")
        blocks.append("\n\n".join(block))
    return "\n\n".join(blocks)


def write_issue(material, date_label):
    prompt = WRITE_PROMPT.format(date=date_label, material=material)
    return llm.ask_json(EDITOR, prompt, WRITE_SCHEMA, effort="high", max_tokens=64000, label="write")


# ---------- stage 3: demos ----------

# A live demo must run the released package itself in the reader's browser. Anything else is a lesson.
DEMO_CDNS = ("https://cdn.jsdelivr.net/", "https://esm.sh/", "https://unpkg.com/")

DEMO_SCHEMA = obj({
    "kind": enum("app", "lesson"),
    "why": STR,
    "package": obj({"ecosystem": enum("npm", "pypi", "none"), "name": STR, "version": STR}),
    "app_html": STR,
    "slides": arr(obj({
        "title": STR, "body": STR, "code": STR,
        "diagram": obj({
            "type": enum("flow", "bars", "tiles"),
            "items": arr(obj({"label": STR, "sub": STR, "value": {"type": "number"},
                              "tone": enum("plain", "accent", "good", "bad", "muted")})),
            "caption": STR,
        }),
    })),
    "try_prompt": STR,
})

DEMO_PROMPT = """A reader has opened this repo feature in the newsletter and wants to understand it in under a \
minute. Build the demo that communicates it best.

Always write the lesson: 3 to 5 slides that build on each other. Every slide is shown in a fixed-size frame, so \
keep to these limits:
- title: at most 45 characters
- body: one or two sentences, at most 200 characters
- diagram: the picture that carries the slide's idea. It is the main thing on the slide, so make it informative. \
You supply the content and the page draws it, so stay inside these limits or text will be cut:
  - type "flow": 2 to 4 steps drawn top to bottom with arrows between them. Use it for a sequence, a request path \
or a before-then-after. Each item: label (at most 40 characters), sub (at most 52, or empty).
  - type "bars": 2 to 4 horizontal bars for comparing sizes, speeds, costs or counts. Each item: label (at most 40 \
characters), value (the number the bar is scaled by), sub (the value as it should be printed, such as "4 bits" or \
"3x faster", at most 14 characters). Only use numbers stated in the release notes.
  - type "tiles": 2 to 6 boxes in a grid for parts, options or settings that sit side by side. Each item: label \
(at most 14 characters), sub (at most 14, or empty).
  - tone marks emphasis: "accent" for the new thing, "good" and "bad" for outcomes, "muted" for what is being \
replaced or skipped, "plain" otherwise. Set value to 0 where it is not used.
  - caption: at most 60 characters, or empty.
- code: at most 2 lines of 44 characters, taken from the release notes, or an empty string. Most slides need none.

Additionally write a live app ONLY if the released code itself can run in a browser tab and exercise this feature:
- an npm package that works in browsers, imported as an ES module from one of {cdns}, pinned to the exact released \
version (for example https://esm.sh/name@1.2.3), or
- a pure-Python package with no native extensions or network needs, installed at the exact released version with \
micropip inside Pyodide (load Pyodide from https://cdn.jsdelivr.net/pyodide/).
The app must call the real package for every result it shows. Re-implementing, simulating or mocking the feature \
in your own code is not allowed, and neither is canned output. If the feature needs a server, a CLI, a GPU, model \
weights, an API key, a database or the file system, or you are not sure the package and this exact version load in \
a browser, a live app is infeasible: set kind to "lesson", leave app_html empty and set package.ecosystem to "none". \
Most releases are lessons; choose "app" only when you are confident.

Rules for app_html when kind is "app":
- one self-contained HTML document with inline CSS and JS; the only network requests allowed are the package and \
its dependencies from the CDNs above
- package must name the ecosystem, the package and the exact version, and the same name and version must appear in \
the import or install line
- after the real package has loaded and produced the first result, call \
parent.postMessage({{demo: "ready", detail: "<name>@<version>"}}, "*"). If loading or running fails, show the error \
in the page and call parent.postMessage({{demo: "error", detail: String(error)}}, "*"). Never send "ready" before the \
package has actually run.
- it runs inside a sandboxed iframe about 340px wide and 420px tall: single column, 16px inputs, no fixed widths
- support light and dark with prefers-color-scheme; plain system fonts; quiet styling, one accent colour
- show a loading line until the package is ready, then open in a filled-in working state so a real result is \
visible before the reader touches anything
- no alert/confirm/prompt, no localStorage, no links, no forms that submit; under 220 lines

try_prompt (always required): one prompt of one or two sentences the reader can paste into Claude Code to try the \
feature in their own project. Name the package and version.

why: one sentence on why a live app is or is not feasible here.

FEATURE
{title}
{summary}

RELEASE NOTES ({repo})
{notes}"""

VERIFY_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>verify</title></head><body>
<iframe sandbox="allow-scripts" style="width:360px;height:440px" srcdoc="{srcdoc}"></iframe>
<img src="/hold" alt="">
<script>addEventListener('message', function(e){{ if(e.data && e.data.demo){{
  fetch('/report?demo=' + encodeURIComponent(e.data.demo) + '&detail=' + encodeURIComponent(String(e.data.detail || '').slice(0, 300))); }} }});</script>
</body></html>"""


def references_real_package(demo):
    """The app must import or install the named package at the named version from an allowed CDN."""
    pkg, page = demo["package"], demo["app_html"]
    if pkg["ecosystem"] == "npm":
        return any(cdn in page for cdn in DEMO_CDNS) and f"{pkg['name']}@{pkg['version']}" in page
    if pkg["ecosystem"] == "pypi":
        return "pyodide" in page and "micropip" in page and f"{pkg['name']}=={pkg['version']}" in page
    return False


def runs_in_browser(app_html, wait=60):
    """Load the app in the same sandbox the site uses and wait for it to report that the real package ran.

    A throwaway local server hands headless Chromium the wrapper page, keeps the page open with a slow
    request, and receives the app's ready or error report.
    """
    result = {}
    done = threading.Event()
    page = VERIFY_PAGE.format(srcdoc=html.escape(app_html, quote=True)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            body = b""
            if url.path == "/":
                body = page
            elif url.path == "/report":
                query = parse_qs(url.query)
                result.setdefault("demo", query.get("demo", [""])[0])
                result.setdefault("detail", query.get("detail", [""])[0])
                done.set()
            elif url.path == "/hold":
                done.wait(wait)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run(["chromium-browser", "--headless", "--disable-gpu", "--no-sandbox", "--dump-dom",
                        f"http://127.0.0.1:{server.server_address[1]}/"],
                       capture_output=True, text=True, timeout=wait + 60)
    except Exception as e:
        result.setdefault("detail", f"browser check did not finish: {e}")
    finally:
        done.set()
        server.shutdown()
    if "demo" not in result:
        return False, result.get("detail") or "the app never reported that the package ran"
    return result["demo"] == "ready", result["detail"]


def build_demo(item, candidate):
    notes = candidate["feed_text"][:12000] if candidate else item["summary"]
    prompt = DEMO_PROMPT.format(title=item["title"], summary=item["summary"], repo=item["repo"], notes=notes,
                                cdns=", ".join(DEMO_CDNS))
    demo = llm.ask_json(EDITOR, prompt, DEMO_SCHEMA, effort="medium", max_tokens=32000, label=f"demo {item['repo']}")
    if demo["kind"] == "app":
        if not references_real_package(demo):
            demo["kind"], demo["why"] = "lesson", "The live app did not load the released package, so it was dropped."
        else:
            ok, detail = runs_in_browser(demo["app_html"])
            if ok:
                demo["verified"] = detail
            else:
                demo["kind"], demo["why"] = "lesson", f"The live app failed its browser check ({detail})."
    for slide in demo["slides"]:
        slide["svg"] = draw_diagram(slide.pop("diagram"))
    if demo["kind"] == "lesson":
        demo["app_html"] = ""
        if not demo["slides"]:
            return None
    return demo


SVG_STYLE = """
svg{fill:none;stroke:none;font-family:system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
.box{stroke-width:1.2}.arrow{stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}
.l{font-size:11px;font-weight:600}.s{font-size:9.5px}
.plain .box{fill:#FAFBFC;stroke:#9AA3B0}.plain .l{fill:#12161C}.plain .bar{fill:#5A6370}
.accent .box{fill:#E8EEFD;stroke:#1F4FD8}.accent .l{fill:#1F4FD8}.accent .bar{fill:#1F4FD8}
.good .box{fill:#E6F4EC;stroke:#1E7F4B}.good .l{fill:#1E7F4B}.good .bar{fill:#1E7F4B}
.bad .box{fill:#FBEAE8;stroke:#B3362B}.bad .l{fill:#B3362B}.bad .bar{fill:#B3362B}
.muted .box{fill:none;stroke:#9AA3B0;stroke-dasharray:3 3}.muted .l{fill:#5A6370}.muted .bar{fill:#8A93A0}
.s,.cap{fill:#5A6370}.cap{font-size:9.5px}.arrow{stroke:#5A6370}.track{fill:#DCE0E6}.bl{fill:#12161C;font-size:11px;font-weight:500}
@media (prefers-color-scheme: dark){
.plain .box{fill:#101318;stroke:#6B7482}.plain .l{fill:#E4E8EE}.plain .bar{fill:#939CAA}
.accent .box{fill:#1B2540;stroke:#86A8FF}.accent .l{fill:#86A8FF}.accent .bar{fill:#86A8FF}
.good .box{fill:#16291F;stroke:#62CE92}.good .l{fill:#62CE92}.good .bar{fill:#62CE92}
.bad .box{fill:#301A18;stroke:#F0867B}.bad .l{fill:#F0867B}.bad .bar{fill:#F0867B}
.muted .box{stroke:#6B7482}.muted .l{fill:#939CAA}.muted .bar{fill:#6B7482}
.s,.cap{fill:#939CAA}.arrow{stroke:#939CAA}.track{fill:#2A303A}.bl{fill:#E4E8EE}}
"""
W, H, PAD = 320, 170, 10


def _fit(text, width, char_px):
    """Cut text to what fits in `width` pixels at an average glyph width."""
    text = " ".join(str(text or "").split())
    limit = max(3, int(width / char_px))
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _wrap(text, width, char_px, lines=2):
    """Greedy word wrap into at most `lines` lines, truncating the last."""
    limit = max(3, int(width / char_px))
    out, row = [], ""
    for word in " ".join(str(text or "").split()).split(" "):
        if len(row) + len(word) + bool(row) <= limit:
            row = f"{row} {word}".strip()
        else:
            out.append(row)
            row = word
    out.append(row)
    out = [r for r in out if r]
    if len(out) > lines:
        out = out[:lines - 1] + [" ".join(out[lines - 1:])]
    return [_fit(r, width, char_px) for r in out]


def draw_diagram(diagram):
    """Lay a slide's diagram out as themed SVG. All positions are computed here so nothing can overlap."""
    esc = lambda t: html.escape(str(t), quote=True)
    kind = diagram["type"]
    items = [i for i in diagram["items"] if str(i.get("label", "")).strip()][: 6 if kind == "tiles" else 4]
    if len(items) < 2:
        return ""
    caption = _fit(diagram.get("caption", ""), W - 2 * PAD, 5.0)
    top, bottom = PAD, H - PAD - (14 if caption else 0)
    area, inner = bottom - top, W - 2 * PAD
    out = []

    if kind == "flow":
        gap = 13
        box_h = min(36, (area - gap * (len(items) - 1)) / len(items))
        y = top + (area - (box_h * len(items) + gap * (len(items) - 1))) / 2
        for n, item in enumerate(items):
            sub = _fit(item["sub"], inner - 24, 5.0) if box_h >= 27 else ""
            label_y = y + (box_h / 2 - 2 if sub else box_h / 2 + 4)
            out.append(f'<g class="{item["tone"]}"><rect class="box" x="{PAD}" y="{y:.1f}" width="{inner}" height="{box_h:.1f}" rx="5"/>'
                       f'<text class="l" x="{PAD + 12}" y="{label_y:.1f}">{esc(_fit(item["label"], inner - 24, 6.4))}</text>'
                       + (f'<text class="s" x="{PAD + 12}" y="{label_y + 12:.1f}">{esc(sub)}</text>' if sub else "") + "</g>")
            if n < len(items) - 1:
                ax, ay = W / 2, y + box_h + 2
                out.append(f'<path class="arrow" d="M{ax} {ay:.1f}V{ay + gap - 5:.1f}M{ax - 4} {ay + gap - 9:.1f}L{ax} {ay + gap - 5:.1f}L{ax + 4} {ay + gap - 9:.1f}"/>')
            y += box_h + gap

    elif kind == "bars":
        row_h = min(44, area / len(items))
        y = top + (area - row_h * len(items)) / 2
        peak = max((abs(float(i["value"])) for i in items), default=0) or 1
        for item in items:
            width = max(4, abs(float(item["value"])) / peak * inner)
            value = _fit(item["sub"], 90, 6.0)
            out.append(f'<g class="{item["tone"]}"><text class="bl" x="{PAD}" y="{y + 12:.1f}">{esc(_fit(item["label"], inner - 96, 6.0))}</text>'
                       f'<text class="l" x="{W - PAD}" y="{y + 12:.1f}" text-anchor="end">{esc(value)}</text>'
                       f'<rect class="track" x="{PAD}" y="{y + 18:.1f}" width="{inner}" height="10" rx="3"/>'
                       f'<rect class="bar" x="{PAD}" y="{y + 18:.1f}" width="{width:.1f}" height="10" rx="3"/></g>')
            y += row_h

    else:  # tiles
        cols = 2 if len(items) <= 4 else 3
        rows = -(-len(items) // cols)
        gap = 8
        tile_w = (inner - gap * (cols - 1)) / cols
        tile_h = min(70, (area - gap * (rows - 1)) / rows)
        y0 = top + (area - (tile_h * rows + gap * (rows - 1))) / 2
        for n, item in enumerate(items):
            x = PAD + (n % cols) * (tile_w + gap)
            y = y0 + (n // cols) * (tile_h + gap)
            label = _wrap(item["label"], tile_w - 12, 6.4, 2 if tile_h >= 44 else 1)
            sub = _fit(item["sub"], tile_w - 12, 5.0) if tile_h >= 34 else ""
            block = len(label) * 13 + (12 if sub else 0)
            ty = y + (tile_h - block) / 2 + 10
            text = "".join(f'<text class="l" x="{x + tile_w / 2:.1f}" y="{ty + 13 * k:.1f}" text-anchor="middle">{esc(row)}</text>'
                           for k, row in enumerate(label))
            if sub:
                text += f'<text class="s" x="{x + tile_w / 2:.1f}" y="{ty + 13 * len(label) + 1:.1f}" text-anchor="middle">{esc(sub)}</text>'
            out.append(f'<g class="{item["tone"]}"><rect class="box" x="{x:.1f}" y="{y:.1f}" width="{tile_w:.1f}" height="{tile_h:.1f}" rx="5"/>{text}</g>')

    if caption:
        out.append(f'<text class="cap" x="{W / 2}" y="{H - PAD}" text-anchor="middle">{esc(caption)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"><style>{SVG_STYLE}</style>'
            + "".join(out) + "</svg>")


# ---------- stage 4: podcast script ----------

# Two hosts argue through a rundown against the clock, in the manner of a sports debate show.
HOSTS = {"A": "Theo", "B": "Maya"}
SHOW_SEGMENTS = ["intro", "business", "discoveries", "blogs", "papers", "repos", "finish"]

SCRIPT_SCHEMA = obj({"segments": arr(obj({
    "id": enum(*SHOW_SEGMENTS),
    "turns": arr(obj({"speaker": enum("A", "B"), "text": STR})),
}))})

SCRIPT_PROMPT = """Write today's episode of the AI Digest podcast: a two-host debate show that races through a \
rundown of topics against the clock, in the format of a daily sports argument show. The hosts are {a} (speaker A) \
and {b} (speaker B). {a} is the sceptic who wants numbers and discounts announcements; {b} is the builder who cares \
what can be shipped this quarter. They like each other, interrupt each other, and genuinely disagree on at least \
half the topics. Neither is a real person and neither imitates one.

Structure, in this order (skip a section that is not in the issue):
- intro: a few quick lines of banter, then one host reads the rundown of what is coming.
- business, discoveries: two or three topics each. One host tosses the headline to the other as a pointed question; \
they trade short takes; a host calls time and moves on.
- blogs: a game of "read it or skip it" using the verdicts. They may disagree with the newsletter's verdict.
- papers: a game of "buy or sell" on whether each paper reaches products within a year.
- repos: "what to try tonight", one pick each with the reason.
- finish: rapid-fire one-liners on anything left over, each host's single takeaway for the day, and a sign-off.

Rules:
- Every fact, number and name must come from the issue below. Opinions and predictions are the hosts' own and \
should sound like opinions.
- Turns are short: mostly one or two sentences, never more than 260 characters. Vary the rhythm; let some turns be \
four words.
- Write for the ear: no lists, urls, symbols or stage directions; say numbers the way a person would; name the \
company or author when you bring up a story so a listener never needs the page.
- The whole script, counting only the spoken text, must come to between {low} and {high} characters. Spread it \
across the segments roughly in proportion to how much each section matters today.

THE ISSUE
{issue}"""


def write_script(issue, max_chars):
    digest = {"subject": issue["subject"], "lead": issue["lead"], "sections": [
        {"id": sec["id"], "name": sec["label"], "items": [
            {k: v for k, v in {"title": item["title"], "by": item.get("author"), "summary": item["summary"],
                               "verdict": item.get("rating", {}).get("label"),
                               "verdict_reason": item.get("rating", {}).get("text")}.items() if v}
            for item in sec["items"]]} for sec in issue["sections"]]}
    prompt = SCRIPT_PROMPT.format(a=HOSTS["A"], b=HOSTS["B"], low=int(max_chars * 0.85), high=max_chars,
                                  issue=json.dumps(digest, indent=1))
    script = llm.ask_json(EDITOR, prompt, SCRIPT_SCHEMA, effort="medium", max_tokens=48000, label="podcast script")
    present = {sec["id"] for sec in issue["sections"]} | {"intro", "finish"}
    return [seg for seg in script["segments"] if seg["id"] in present and seg["turns"]]


# ---------- assembly ----------

def _links(raw, allowed):
    """Keep only links that point at urls we actually supplied to the model."""
    out, seen = [], set()
    for link in raw:
        url = link["url"].strip()
        if url in allowed and url not in seen:
            seen.add(url)
            out.append({"label": link["label"].strip() or "Source", "url": url,
                        "domain": allowed[url]})
    return out


def assemble(written, demos, by_id, date):
    def domain(c):
        host = urlparse(c["url"]).netloc.removeprefix("www.")
        return c["source"].split(":")[0] if host == "news.google.com" else host
    allowed = {c["url"]: domain(c) for c in by_id.values()}

    sections = []
    for key, tag, label in SECTIONS:
        items = []
        for raw in written[key]["items"]:
            item = {"title": raw["title"], "summary": raw["summary"], "links": _links(raw["links"], allowed)}
            if key == "blogs":
                item["author"] = raw["author"]
                item["rating"] = {"heading": "Claude's read", "label": raw["verdict"],
                                  "n": RATING[raw["verdict"]], "text": raw["critique"]}
            elif key == "papers":
                item["author"] = raw["traction"]
                item["rating"] = {"heading": "Industry potential", "label": raw["potential"],
                                  "n": RATING[raw["potential"]], "text": raw["rationale"]}
            elif key == "repos":
                item["repo"] = raw["repo"]
                demo = demos.get(raw["source_id"])
                if demo:
                    item["demo"] = demo
                    item["side"] = "live demo" if demo["kind"] == "app" else "lesson"
            if key in ("business", "discoveries"):
                n = len(item["links"])
                item["side"] = f"{n} source{'s' if n != 1 else ''}" if n else ""
            if item["links"] or key == "repos":
                items.append(item)
        if items:
            sections.append({"id": key, "tag": tag, "label": label, "brief": written[key]["brief"], "items": items})

    return {
        "date": date.strftime("%Y-%m-%d"),
        "date_label": date.strftime("%a %-d %b %Y"),
        "date_long": date.strftime("%A %-d %B %Y"),
        "subject": written["subject"],
        "lead": written["lead"],
        "sections": sections,
        "podcast": None,
    }


def used_urls(issue):
    return [link["url"] for sec in issue["sections"] for item in sec["items"] for link in item["links"]]


# ---------- site ----------

def render_site(issue):
    """Write the issue page, refresh the home page and the archive list."""
    issue_dir = SITE / "issues" / issue["date"]
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "issue.json").write_text(json.dumps(issue, indent=1))

    archive = []
    for path in sorted((SITE / "issues").glob("*/issue.json"), reverse=True):
        past = json.loads(path.read_text())
        archive.append({"date": past["date"], "label": past["date_label"], "subject": past["subject"]})

    template = TEMPLATE.read_text()

    def page(data):
        blob = json.dumps({"issue": data, "archive": archive}).replace("</", "<\\/")
        return (template.replace("__TITLE__", html.escape(f"AI Digest · {data['date_label']}"))
                .replace("__DESCRIPTION__", html.escape(data["subject"], quote=True))
                .replace("__DATA__", blob))

    for path in (SITE / "issues").glob("*/issue.json"):
        (path.parent / "index.html").write_text(page(json.loads(path.read_text())))
    (SITE / "index.html").write_text(page(issue))
    return issue_dir


def deploy():
    result = subprocess.run([str(DEPLOY_SCRIPT), str(SITE), "--prod", "--name", PROJECT_NAME],
                            capture_output=True, text=True)
    match = re.search(r"^URL: (\S+)", result.stdout, re.M)
    if result.returncode != 0 or not match:
        raise RuntimeError("deploy failed:\n" + result.stderr[-1500:])
    return match.group(1).rstrip("/")


# ---------- email ----------

def email_bodies(issue, site_url, recipient, worker_url):
    link = f"{site_url}/issues/{issue['date']}/"
    esc = html.escape
    total = sum(len(s["items"]) for s in issue["sections"])
    rows = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;vertical-align:top;font:600 11px ui-monospace,Menlo,monospace;'
        f'color:#1F4FD8;letter-spacing:.04em;white-space:nowrap">{s["tag"]}</td>'
        f'<td style="padding:6px 0;font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#12161C">'
        f'{esc(s["brief"])}</td></tr>' for s in issue["sections"])
    listen = ""
    if issue["podcast"]:
        minutes = max(1, round(issue["podcast"]["duration"] / 60))
        listen = (f'<p style="margin:10px 0 0;text-align:center;font:14px -apple-system,Segoe UI,Helvetica,Arial,'
                  f'sans-serif"><a href="{link}#listen" style="color:#1F4FD8">Listen instead, {minutes} min</a></p>')
    unsub = f"{worker_url}/unsubscribe?email={quote(recipient)}" if worker_url else ""
    footer = f'<a href="{unsub}" style="color:#5A6370">Unsubscribe</a>' if unsub else ""
    body = f"""<html><body style="margin:0;padding:24px 16px;background:#FAFBFC">
<div style="max-width:520px;margin:0 auto">
<p style="margin:0 0 4px;font:600 12px ui-monospace,Menlo,monospace;color:#5A6370">AI DIGEST · {esc(issue['date_label'])}</p>
<h1 style="margin:0 0 12px;font:600 21px/1.25 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#12161C">{esc(issue['subject'])}</h1>
<p style="margin:0 0 14px;font:16px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#12161C">{esc(issue['lead'])}</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="border-top:2px solid #12161C;width:100%">{rows}</table>
<p style="margin:18px 0 0"><a href="{link}" style="display:block;text-align:center;background:#12161C;color:#FAFBFC;text-decoration:none;padding:13px;border-radius:6px;font:600 15px -apple-system,Segoe UI,Helvetica,Arial,sans-serif">Open the full issue · {total} items</a></p>
{listen}
<p style="margin:22px 0 0;text-align:center;font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#5A6370">Verdicts, sources and demos are on the web version. {footer}</p>
</div></body></html>"""
    text = f"AI Digest, {issue['date_label']}\n\n{issue['subject']}\n\n{issue['lead']}\n\n"
    text += "".join(f"{s['tag']}: {s['brief']}\n" for s in issue["sections"])
    text += f"\nFull issue ({total} items): {link}\n"
    if unsub:
        text += f"\nUnsubscribe: {unsub}\n"
    return text, body, unsub


def send_emails(issue, site_url, mode):
    smtp_user = os.getenv("SMTP_USER", "")
    worker_url = os.getenv("WORKER_URL", "")
    if mode == "test":
        recipients = [smtp_user]
    else:
        from blog_digest import load_state
        unsubscribed = set(load_state().get("unsubscribed", []))
        recipients = [r.strip() for r in os.getenv("EMAIL_TO", "").split(",") if r.strip() and r.strip() not in unsubscribed]
    if not recipients or not smtp_user:
        print("  no recipients, email skipped")
        return
    messages = []
    for recipient in recipients:
        text, body, unsub = email_bodies(issue, site_url, recipient, worker_url)
        headers = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if unsub else {}
        messages.append(mailer.build_message(subject=f"{SUBJECT_MARKER} {issue['subject']}", sender=smtp_user, recipient=recipient,
                                             text=text, html=body, extra_headers=headers))
    mailer.send_messages(messages)
    print(f"  emailed {len(recipients)} recipient(s) ({mode})")


# ---------- run ----------

def cached(path, resume, make):
    if resume and path.exists():
        print(f"  reusing {path.name}")
        return json.loads(path.read_text())
    value = make()
    path.write_text(json.dumps(value, indent=1))
    return value


def main():
    parser = argparse.ArgumentParser(description="Build, publish and send one AI Digest issue")
    parser.add_argument("--resume", action="store_true", help="reuse stages cached by an earlier run today")
    parser.add_argument("--deploy", action="store_true", help="publish the site to Vercel")
    parser.add_argument("--email", choices=["none", "test", "all"], default="none",
                        help="test sends to SMTP_USER only; all sends to EMAIL_TO")
    parser.add_argument("--podcast", action="store_true", help="also write and record the two-host podcast (off by default)")
    parser.add_argument("--podcast-chars", type=int, default=int(os.getenv("PODCAST_MAX_CHARS", "19000")),
                        help="length of the spoken script; about 900 characters per minute")
    args = parser.parse_args()

    mailer.load_env_file()
    date = datetime.now()
    work = WORK / date.strftime("%Y-%m-%d")
    work.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"used_urls": [], "site_url": ""}
    today_key = date.strftime("%Y-%m-%d")
    exclude = [u for day, urls in state.get("used_by_day", {}).items() if day != today_key for u in urls]

    print("Gathering candidates")
    candidates = cached(work / "candidates.json", args.resume, lambda: sources.fetch_all(exclude))
    by_id = {c["id"]: c for c in candidates}

    print(f"Curating {len(candidates)} candidates")
    picks = cached(work / "picks.json", args.resume, lambda: curate(candidates))

    print("Reading sources and writing the issue")
    written = cached(work / "written.json", args.resume,
                     lambda: write_issue(gather_material(picks, by_id), date.strftime("%A %-d %B %Y")))

    print("Building repo demos")
    def make_demos():
        demos = {}
        for item in written["repos"]["items"]:
            try:
                demo = build_demo(item, by_id.get(item["source_id"]))
            except Exception as e:
                print(f"  demo failed for {item['repo']}: {e}")
                demo = None
            if demo:
                print(f"  {item['repo']}: {demo['kind']} ({demo['why']})")
                demos[item["source_id"]] = demo
        return demos
    demos = cached(work / "demos.json", args.resume, make_demos)

    issue = assemble(written, demos, by_id, date)

    if args.podcast:
        print("Writing and recording the podcast")
        segments = cached(work / "script.json", args.resume, lambda: write_script(issue, args.podcast_chars))
        audio = SITE / "issues" / issue["date"] / "podcast.mp3"
        meta_path = work / "podcast.json"
        if args.resume and meta_path.exists() and audio.exists():
            meta = json.loads(meta_path.read_text())
        else:
            meta = podcast.make_podcast(segments, audio)
            if meta:
                meta_path.write_text(json.dumps(meta))
        if meta:
            tags = {sec["id"]: sec["tag"] for sec in issue["sections"]} | {"intro": "INTRO", "finish": "FINISH"}
            issue["podcast"] = {"src": f"/issues/{issue['date']}/podcast.mp3", "duration": meta["duration"],
                                "hosts": list(HOSTS.values()),
                                "chapters": [{"id": c["id"], "tag": tags[c["id"]], "t": c["t"]} for c in meta["chapters"]]}

    print("Rendering the site")
    issue_dir = render_site(issue)
    print(f"  {issue_dir / 'index.html'}")

    state.setdefault("used_by_day", {})[today_key] = used_urls(issue)
    state["used_by_day"] = dict(sorted(state["used_by_day"].items())[-14:])

    if args.deploy:
        print("Deploying")
        state["site_url"] = deploy()
        print(f"  {state['site_url']}")
    STATE_FILE.write_text(json.dumps(state, indent=1))

    if args.email != "none":
        if not state.get("site_url"):
            raise SystemExit("No site URL yet: run with --deploy before sending email")
        send_emails(issue, state["site_url"], args.email)

    cost = sum(u["input"] * 4 + u["output"] * 20 for u in llm.usage_log) / 1e6
    print(f"Done: {sum(len(s['items']) for s in issue['sections'])} items, "
          f"{len(llm.usage_log)} model calls, about ${cost:.2f}")


if __name__ == "__main__":
    main()
