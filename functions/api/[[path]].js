/**
 * Cloudflare Pages Function: proxies all /api/* requests (including multipart
 * notice uploads and SSE streams) to the Python FastAPI backend at BACKEND_URL.
 */
export async function onRequest(context) {
  const { request, env } = context;
  const backendUrl = (env.BACKEND_URL || '').replace(/\/+$/, '');

  if (!backendUrl) {
    return new Response(
      JSON.stringify({
        detail:
          'BACKEND_URL is not configured on Cloudflare Pages. Set BACKEND_URL to your FastAPI backend or Cloudflare Tunnel URL.',
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }

  const incomingUrl = new URL(request.url);
  const targetUrl = `${backendUrl}${incomingUrl.pathname}${incomingUrl.search}`;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.set('x-forwarded-host', incomingUrl.host);
  headers.set('x-forwarded-proto', incomingUrl.protocol.replace(':', ''));

  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
  };

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
    init.duplex = 'half';
  }

  const upstream = await fetch(targetUrl, init);
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete('content-encoding');

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}
