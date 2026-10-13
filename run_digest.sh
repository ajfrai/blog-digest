#!/bin/bash
# Daily AI Digest: build the issue, publish the site, send the skinny email.
# ANTHROPIC_API_KEY lives in ~/.zshenv; everything else in .blog_digest_env.
[ -f ~/.zshenv ] && source ~/.zshenv
[ -f ~/blog_digest/.blog_digest_env ] && source ~/blog_digest/.blog_digest_env
cd ~/blog_digest && .venv/bin/python build_issue.py --deploy --email all "$@"
