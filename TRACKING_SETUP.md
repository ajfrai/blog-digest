# Blog Digest Click Tracking Setup

This guide explains how to set up click tracking and downvoting for your blog digest using Cloudflare Workers + Workers KV.

## Architecture Overview

1. **Cloudflare Worker**: Handles HTTP requests for tracking clicks and downvotes
2. **Workers KV**: Stores state (clicked and downvoted article IDs) in the cloud
3. **Local Script**: Fetches state from KV before running, generates digest with tracking links

### Benefits of This Approach

- **Serverless**: No local server to maintain
- **Globally distributed**: Fast redirects from anywhere
- **Free tier**: 100k requests/day, plenty for personal use
- **Stateless**: Worker just reads/writes to KV, no complex state management
- **Educational**: Learn edge computing, distributed systems, and modern web architecture

## Setup Steps

### 1. Create Cloudflare Account

1. Go to https://dash.cloudflare.com/sign-up
2. Create a free account (no credit card required for Workers free tier)
3. Verify your email

### 2. Create a Worker

1. Go to https://dash.cloudflare.com/ and select "Workers & Pages"
2. Click "Create Application" → "Create Worker"
3. Name it something like `blog-digest-tracker`
4. Click "Deploy" (we'll update the code in the next step)

### 3. Deploy the Worker Code

1. After deployment, click "Edit Code"
2. Delete the default code
3. Copy the contents of `worker.js` from this folder
4. Paste it into the editor
5. Click "Save and Deploy"

### 4. Create KV Namespace

1. In Cloudflare dashboard, go to "Workers & Pages" → "KV"
2. Click "Create a namespace"
3. Name it `BLOG_STATE`
4. Note the namespace ID

### 5. Bind KV Namespace to Worker

1. Go back to your Worker
2. Click "Settings" → "Variables"
3. Under "KV Namespace Bindings", click "Add binding"
4. Variable name: `BLOG_STATE`
5. KV namespace: Select the namespace you just created
6. Click "Save"

### 6. Get Your Worker URL

Your Worker URL will be something like:
```
https://blog-digest-tracker.YOUR-SUBDOMAIN.workers.dev
```

You can find this on your Worker's page in the Cloudflare dashboard.

### 7. Configure Local Environment

Add the Worker URL to your `.blog_digest_env` file:

```bash
export WORKER_URL='https://blog-digest-tracker.YOUR-SUBDOMAIN.workers.dev'
```

### 8. Test the Setup

Run a test digest:

```bash
cd ~/blog_digest
source .blog_digest_env
python3 blog_digest.py --max-age-days 60
```

Check your email - article links should now go through your Worker (you'll see the redirect URL in your browser's address bar briefly before redirecting to the actual article).

## How It Works

### When You Receive a Digest Email

1. Click on an article link
2. Your browser sends request to Worker: `/track?id=ARTICLE_ID&url=TARGET_URL`
3. Worker adds article ID to "clicked" list in KV
4. Worker redirects you to the actual article
5. Next digest will exclude this article

### When You Downvote

1. Click "👎 Not interested" link
2. Your browser sends request to Worker: `/downvote?id=ARTICLE_ID`
3. Worker adds article ID to "downvoted" list (and "clicked" list)
4. Worker returns success message
5. Next digest will exclude this article

### When Digest Runs

1. Script calls Worker: `/api/state`
2. Worker returns list of clicked and downvoted article IDs
3. Script merges with local state
4. Articles in either list are excluded from the digest
5. New digest is generated and sent

## State Management

- **Workers KV**: Primary source of truth for clicked/downvoted articles
- **Local state file**: Backup and for offline operation
- State is synced on every digest run
- Articles remain excluded until you manually clear the state

## Monitoring

### Check Worker Logs

1. Go to your Worker in Cloudflare dashboard
2. Click "Logs" → "Begin log stream"
3. Click on articles in your email to see requests being logged

### Check KV Data

1. Go to "Workers & Pages" → "KV"
2. Click on your `BLOG_STATE` namespace
3. Click on the "state" key to view stored data
4. You'll see JSON with clicked and downvoted article IDs

### Check API Endpoint

Visit `https://YOUR-WORKER-URL.workers.dev/api/state` in your browser to see current state.

## Manual State Management

### Clear All Tracking

To reset and see all articles again:

```bash
# Using curl
curl https://YOUR-WORKER-URL.workers.dev/api/state

# Manually delete the KV entry via dashboard:
# Go to KV → BLOG_STATE → delete "state" key
```

### Remove Specific Article

1. Fetch current state from Worker API
2. Edit the JSON to remove specific article IDs
3. Update KV via Cloudflare dashboard or API

## Troubleshooting

### Articles still showing up after clicking

- Check Worker logs to ensure tracking request succeeded
- Verify KV binding is configured correctly
- Check that WORKER_URL is set in your environment

### Redirects not working

- Verify Worker is deployed and accessible
- Check URL encoding in email links
- Test Worker directly: `curl "https://YOUR-WORKER-URL.workers.dev/track?id=test&url=https://example.com"`

### State not syncing

- Check that script can reach Worker URL (test with curl)
- Verify KV namespace is bound to Worker
- Check for errors in script output when it runs

## Cost

Cloudflare Workers free tier includes:
- **100,000 requests/day**: More than enough for personal use
- **Workers KV**: 100,000 reads/day, 1,000 writes/day, 1 GB storage
- No credit card required

For a daily digest with 10 articles:
- Daily cost: ~10 reads (state fetch) + up to 10 writes (clicks) = 20 operations
- Monthly cost: ~600 operations (well within free tier)

## Learning Resources

- **Cloudflare Workers Docs**: https://developers.cloudflare.com/workers/
- **Workers KV Docs**: https://developers.cloudflare.com/kv/
- **Edge Computing Concepts**: https://www.cloudflare.com/learning/serverless/glossary/what-is-edge-computing/

## Advanced: Custom Domain (Optional)

If you have a domain on Cloudflare:

1. Go to your Worker settings
2. Click "Triggers" → "Add Custom Domain"
3. Enter a subdomain like `track.yourdomain.com`
4. Update WORKER_URL in your `.blog_digest_env`

This gives you a cleaner URL and hides the `workers.dev` domain.
