#!/bin/bash
# Quick deployment script for Cloudflare Worker
# Requires: npm/npx installed

set -e

echo "Blog Digest Tracker - Worker Deployment"
echo "========================================"
echo ""

# Check if wrangler is available
if ! command -v npx &> /dev/null; then
    echo "Error: npx not found. Please install Node.js first."
    echo "Install with: sudo apt install nodejs npm"
    exit 1
fi

echo "Step 1: Login to Cloudflare"
echo "This will open a browser for authentication..."
npx wrangler login

echo ""
echo "Step 2: Create KV namespace"
echo "Creating KV namespace 'BLOG_STATE'..."
KV_OUTPUT=$(npx wrangler kv:namespace create "BLOG_STATE")
echo "$KV_OUTPUT"

# Extract namespace ID from output
KV_ID=$(echo "$KV_OUTPUT" | grep -oP 'id = "\K[^"]+' | head -1)

if [ -z "$KV_ID" ]; then
    echo "Warning: Could not automatically extract KV namespace ID."
    echo "Please update wrangler.toml manually with your namespace ID."
    echo ""
    read -p "Enter your KV namespace ID (or press Enter to skip): " MANUAL_KV_ID
    if [ ! -z "$MANUAL_KV_ID" ]; then
        KV_ID="$MANUAL_KV_ID"
    fi
fi

if [ ! -z "$KV_ID" ]; then
    echo "Updating wrangler.toml with KV namespace ID: $KV_ID"
    sed -i "s/YOUR_KV_NAMESPACE_ID/$KV_ID/" wrangler.toml
fi

echo ""
echo "Step 3: Deploy Worker"
npx wrangler deploy

echo ""
echo "=========================================="
echo "Deployment complete!"
echo ""
echo "Your Worker is now live. To finish setup:"
echo "1. Note your Worker URL (shown above)"
echo "2. Add it to .blog_digest_env:"
echo "   export WORKER_URL='https://blog-digest-tracker.YOUR-SUBDOMAIN.workers.dev'"
echo "3. Test it: source .blog_digest_env && python3 blog_digest.py --max-age-days 60"
echo ""
echo "See TRACKING_SETUP.md for more details."
