export async function onRequest(context) {
  const { env } = context;
  const backendUrl = (env.BACKEND_URL || '').replace(/\/+$/, '');

  if (!backendUrl) {
    return new Response(
      JSON.stringify({ status: 'frontend_ok', backend: 'unconfigured' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const upstream = await fetch(`${backendUrl}/healthz`);
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
