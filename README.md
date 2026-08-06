# Daily AI Blog Digest

Automated script that sends you 10 blog articles daily from top AI research blogs, with smart tracking that excludes articles you've read or downvoted.

## Blogs Monitored

- Anthropic (Research, Engineering, News)
- Google DeepMind
- Google Research
- OpenAI
- Cursor
- Simon Willison
- Ethan Mollick (One Useful Thing)
- Hugging Face
- Andrey Karpathy

## Quick Setup

### 1. Run the setup script

```bash
chmod +x ~/setup_blog_digest.sh
~/setup_blog_digest.sh
```

### 2. Configure email credentials

Create `~/.blog_digest_env` with your email settings:

```bash
nano ~/.blog_digest_env
```

Add the following (replace with your details):

```bash
export SMTP_SERVER='smtp.gmail.com'
export SMTP_PORT='587'
export SMTP_USER='your-email@gmail.com'
export SMTP_PASSWORD='your-app-password'
```

#### For Gmail users:

1. Enable 2-factor authentication on your Google account
2. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Generate an "App Password" for "Mail"
4. Use that 16-character password in the config above

#### For other email providers:

- **Outlook/Hotmail**: `smtp.office365.com`, port `587`
- **Yahoo**: `smtp.mail.yahoo.com`, port `587`
- **Custom SMTP**: Contact your email provider for SMTP settings

### 3. Test the script

```bash
~/run_blog_digest.sh
```

You should receive an email with 3 articles at ajfraifeld@gmail.com

## How It Works

- Runs daily at 4 AM (configurable)
- Fetches latest articles from all blogs (within past 7 days)
- Excludes articles you've already clicked or downvoted
- Sends 10 new articles with tracking links
- Nicely formatted HTML email with "Not interested" buttons

## Smart Tracking (Optional)

By default, articles are shown once per digest. For smarter tracking that persists across runs:

1. **Click tracking**: Articles you open are automatically marked as read
2. **Downvoting**: Click "👎 Not interested" to hide articles without reading
3. **Cloud-based state**: Tracking works from any device via Cloudflare Workers

**To enable tracking**, see `TRACKING_SETUP.md` for detailed setup instructions. This requires:
- Free Cloudflare account (no credit card needed)
- 10 minutes of setup time
- Deploys a serverless function to track your interactions

Without tracking, the script still works but shows articles only once.

## Configuration

### Change the schedule

Edit your crontab:

```bash
crontab -e
```

Current schedule: `0 8 * * *` (8 AM daily)

Examples:
- `0 20 * * *` - 8 PM daily
- `0 9 * * 1-5` - 9 AM on weekdays only
- `0 7,19 * * *` - 7 AM and 7 PM daily

### Change number of articles

Edit `blog_digest.py` and change:

```python
ARTICLES_PER_DAY = 3
```

### Add/remove blogs

Edit the `BLOGS` dictionary in `blog_digest.py`:

```python
BLOGS = {
    "Blog Name": "https://example.com/feed.rss",
}
```

## Troubleshooting

### Check if it's running

```bash
cat ~/blog_digest.log
```

### Test manually

```bash
~/run_blog_digest.sh
```

### Check cron job

```bash
crontab -l
```

### No emails arriving?

1. Check spam folder
2. Verify email credentials in `~/.blog_digest_env`
3. For Gmail, ensure App Password is correct (not your regular password)
4. Check logs: `cat ~/blog_digest.log`

### Reset state (resend old articles)

```bash
rm ~/.blog_digest_state.json
```

## Files

- `~/blog_digest.py` - Main script
- `~/run_blog_digest.sh` - Wrapper that loads credentials
- `~/setup_blog_digest.sh` - Setup script
- `~/.blog_digest_env` - Your email credentials (keep private!)
- `~/.blog_digest_state.json` - Tracks sent articles
- `~/blog_digest.log` - Execution logs

## Uninstall

```bash
crontab -l | grep -v "run_blog_digest.sh" | crontab -
rm ~/blog_digest.py ~/run_blog_digest.sh ~/setup_blog_digest.sh
rm ~/.blog_digest_env ~/.blog_digest_state.json ~/blog_digest.log
```
