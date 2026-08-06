// Cloudflare Worker for tracking article clicks and downvotes
// Deploy this to Cloudflare Workers

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS headers for API requests
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // Route: /track?id=ARTICLE_ID&url=TARGET_URL
    // Marks article as read and redirects to the article
    if (url.pathname === '/track') {
      const articleId = url.searchParams.get('id');
      const targetUrl = url.searchParams.get('url');

      if (!articleId || !targetUrl) {
        return new Response('Missing id or url parameter', { status: 400 });
      }

      try {
        // Get current state from KV
        const stateJson = await env.BLOG_STATE.get('state') || '{"clicked":[],"downvoted":[]}';
        const state = JSON.parse(stateJson);

        // Add to clicked list if not already there
        if (!state.clicked.includes(articleId)) {
          state.clicked.push(articleId);
        }

        // Save updated state
        await env.BLOG_STATE.put('state', JSON.stringify(state));

        // Redirect to the actual article
        return Response.redirect(targetUrl, 302);
      } catch (error) {
        console.error('Error tracking click:', error);
        // Still redirect even if tracking fails
        return Response.redirect(targetUrl, 302);
      }
    }

    // Route: /downvote?id=ARTICLE_ID
    // Marks article as downvoted
    if (url.pathname === '/downvote') {
      const articleId = url.searchParams.get('id');

      if (!articleId) {
        return new Response('Missing id parameter', { status: 400 });
      }

      try {
        // Get current state from KV
        const stateJson = await env.BLOG_STATE.get('state') || '{"clicked":[],"downvoted":[]}';
        const state = JSON.parse(stateJson);

        // Add to downvoted list if not already there
        if (!state.downvoted.includes(articleId)) {
          state.downvoted.push(articleId);
        }

        // Also mark as clicked (implicit read when downvoting)
        if (!state.clicked.includes(articleId)) {
          state.clicked.push(articleId);
        }

        // Save updated state
        await env.BLOG_STATE.put('state', JSON.stringify(state));

        return new Response('Article downvoted', {
          status: 200,
          headers: { ...corsHeaders, 'Content-Type': 'text/plain' }
        });
      } catch (error) {
        console.error('Error downvoting:', error);
        return new Response('Error downvoting article', { status: 500 });
      }
    }

    // Route: /api/state
    // Returns current state (for the digest script to fetch)
    if (url.pathname === '/api/state') {
      try {
        const stateJson = await env.BLOG_STATE.get('state') || '{"clicked":[],"downvoted":[]}';
        return new Response(stateJson, {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      } catch (error) {
        console.error('Error fetching state:', error);
        return new Response('Error fetching state', { status: 500 });
      }
    }

    // Route: /unsubscribe?email=EMAIL
    // Adds email to unsubscribed list and shows confirmation
    if (url.pathname === '/unsubscribe') {
      const email = url.searchParams.get('email');

      if (!email) {
        return new Response('Missing email parameter', { status: 400 });
      }

      try {
        const unsubJson = await env.BLOG_STATE.get('unsubscribed') || '[]';
        const unsubscribed = JSON.parse(unsubJson);

        if (!unsubscribed.includes(email)) {
          unsubscribed.push(email);
          await env.BLOG_STATE.put('unsubscribed', JSON.stringify(unsubscribed));
        }

        return new Response(`
          <html>
            <head><title>Unsubscribed</title></head>
            <body style="font-family:Arial,sans-serif;max-width:600px;margin:60px auto;text-align:center;">
              <h1>You've been unsubscribed</h1>
              <p>${email} has been removed from the daily AI blog digest.</p>
            </body>
          </html>
        `, { headers: { 'Content-Type': 'text/html' } });
      } catch (error) {
        console.error('Error unsubscribing:', error);
        return new Response('Error processing unsubscribe request', { status: 500 });
      }
    }

    // Route: /api/unsubscribed
    // Returns list of unsubscribed emails
    if (url.pathname === '/api/unsubscribed') {
      try {
        const unsubJson = await env.BLOG_STATE.get('unsubscribed') || '[]';
        return new Response(unsubJson, {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      } catch (error) {
        console.error('Error fetching unsubscribed list:', error);
        return new Response('Error fetching unsubscribed list', { status: 500 });
      }
    }

    // Route: /api/clear
    // Clears all tracking state
    if (url.pathname === '/api/clear') {
      try {
        await env.BLOG_STATE.put('state', '{"clicked":[],"downvoted":[]}');
        return new Response('State cleared successfully', {
          headers: { ...corsHeaders, 'Content-Type': 'text/plain' }
        });
      } catch (error) {
        console.error('Error clearing state:', error);
        return new Response('Error clearing state', { status: 500 });
      }
    }

    // Default: show info page
    return new Response(`
      <html>
        <head><title>Blog Digest Tracker</title></head>
        <body>
          <h1>Blog Digest Article Tracker</h1>
          <p>This service tracks article clicks and downvotes for your blog digest.</p>
          <h2>Endpoints:</h2>
          <ul>
            <li><code>/track?id=ARTICLE_ID&url=TARGET_URL</code> - Track click and redirect</li>
            <li><code>/downvote?id=ARTICLE_ID</code> - Mark article as downvoted</li>
            <li><code>/api/state</code> - Get current state (clicked and downvoted articles)</li>
          </ul>
        </body>
      </html>
    `, {
      headers: { 'Content-Type': 'text/html' }
    });
  }
};
