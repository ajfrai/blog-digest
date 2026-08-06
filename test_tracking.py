#!/usr/bin/env python3
"""
Test script to verify Cloudflare Worker tracking is working
"""

import os
import sys
import requests
import json
from urllib.parse import quote

# Load environment
WORKER_URL = os.getenv("WORKER_URL")

if not WORKER_URL:
    print("Error: WORKER_URL not set in environment")
    print("Run: source .blog_digest_env")
    sys.exit(1)

print(f"Testing Worker at: {WORKER_URL}\n")

# Test 1: Check Worker is accessible
print("Test 1: Worker accessibility")
try:
    response = requests.get(WORKER_URL, timeout=5)
    if response.status_code == 200:
        print("✓ Worker is accessible")
    else:
        print(f"✗ Unexpected status code: {response.status_code}")
except Exception as e:
    print(f"✗ Error accessing Worker: {e}")
    sys.exit(1)

# Test 2: Check API state endpoint
print("\nTest 2: API state endpoint")
try:
    response = requests.get(f"{WORKER_URL}/api/state", timeout=5)
    if response.status_code == 200:
        state = response.json()
        print(f"✓ State API working")
        print(f"  Clicked articles: {len(state.get('clicked', []))}")
        print(f"  Downvoted articles: {len(state.get('downvoted', []))}")
    else:
        print(f"✗ API returned status {response.status_code}")
except Exception as e:
    print(f"✗ Error calling API: {e}")
    sys.exit(1)

# Test 3: Test tracking redirect
print("\nTest 3: Track click (redirect)")
test_id = "test-article-123"
test_url = "https://example.com"
track_url = f"{WORKER_URL}/track?id={quote(test_id)}&url={quote(test_url)}"

try:
    # Don't follow redirects automatically so we can verify it's working
    response = requests.get(track_url, allow_redirects=False, timeout=5)
    if response.status_code == 302:
        print("✓ Tracking redirect working")
        print(f"  Redirects to: {response.headers.get('Location')}")
    else:
        print(f"✗ Expected 302 redirect, got {response.status_code}")
except Exception as e:
    print(f"✗ Error testing tracking: {e}")

# Test 4: Verify article was tracked
print("\nTest 4: Verify article was tracked in state")
try:
    response = requests.get(f"{WORKER_URL}/api/state", timeout=5)
    state = response.json()
    if test_id in state.get('clicked', []):
        print(f"✓ Article '{test_id}' was tracked successfully")
    else:
        print(f"✗ Article '{test_id}' not found in clicked list")
        print(f"  Current clicked list: {state.get('clicked', [])}")
except Exception as e:
    print(f"✗ Error verifying state: {e}")

# Test 5: Test downvote
print("\nTest 5: Test downvote")
test_id_2 = "test-article-456"
downvote_url = f"{WORKER_URL}/downvote?id={quote(test_id_2)}"

try:
    response = requests.get(downvote_url, timeout=5)
    if response.status_code == 200:
        print("✓ Downvote endpoint working")
    else:
        print(f"✗ Downvote returned status {response.status_code}")
except Exception as e:
    print(f"✗ Error testing downvote: {e}")

# Test 6: Verify downvote was recorded
print("\nTest 6: Verify downvote was recorded")
try:
    response = requests.get(f"{WORKER_URL}/api/state", timeout=5)
    state = response.json()
    if test_id_2 in state.get('downvoted', []):
        print(f"✓ Article '{test_id_2}' was downvoted successfully")
    else:
        print(f"✗ Article '{test_id_2}' not found in downvoted list")
        print(f"  Current downvoted list: {state.get('downvoted', [])}")
except Exception as e:
    print(f"✗ Error verifying downvote: {e}")

print("\n" + "="*50)
print("Testing complete!")
print("\nCurrent state summary:")
try:
    response = requests.get(f"{WORKER_URL}/api/state", timeout=5)
    state = response.json()
    print(f"  Total clicked: {len(state.get('clicked', []))}")
    print(f"  Total downvoted: {len(state.get('downvoted', []))}")
except:
    pass

print("\nNext steps:")
print("1. Run a test digest: python3 blog_digest.py --max-age-days 60")
print("2. Check your email for tracking links")
print("3. Click on an article and verify it's tracked")
print("4. Run the digest again - clicked articles should be excluded")
