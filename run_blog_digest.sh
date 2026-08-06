#!/bin/bash
# Load environment variables
if [ -f ~/blog_digest/.blog_digest_env ]; then
    source ~/blog_digest/.blog_digest_env
fi
# Run the script
python3 ~/blog_digest/blog_digest.py
