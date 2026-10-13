#!/bin/bash
# Daily AI Digest: build the issue, publish the site, send the skinny email.
# ANTHROPIC_API_KEY lives in ~/.zshenv; everything else in .blog_digest_env.
# cron has no nvm; the system node (v12) is too old for the vercel CLI.
NODE_BIN=$(ls -d ~/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$NODE_BIN" ] && export PATH="$NODE_BIN:$PATH"
export PATH="$HOME/.local/bin:$PATH"  # the claude CLI (subscription auth) lives here
[ -f ~/.zshenv ] && source ~/.zshenv
[ -f ~/blog_digest/.blog_digest_env ] && source ~/blog_digest/.blog_digest_env
cd ~/blog_digest && .venv/bin/python build_issue.py --deploy --email all "$@"
