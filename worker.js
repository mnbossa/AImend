addEventListener('fetch', event => {
  event.respondWith(handle(event.request));
});

async function handle(request) {
  if (request.method !== 'POST') return new Response('Only POST', { status: 405 });

  let url = new URL(request.url);
  if (!url.pathname.startsWith('/chat')) return new Response('Not found', { status: 404 });

  let body;
  try {
    body = await request.json();
  } catch {
    return new Response('Invalid JSON', { status: 400 });
  }
  const prompt = (body.prompt || '').toString();
  if (!prompt) return new Response('Missing prompt', { status: 400 });

  const OPENAI_API_KEY = SECRET_OPENAI_API_KEY; // bound secret in Cloudflare's UI

  // Adjust the OpenAI endpoint as needed. This example uses the Chat Completions endpoint.
  const openaiResp = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENAI_API_KEY}`
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini', // or 'gpt-4o', 'gpt-3.5-turbo' - pick what your account supports
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 800
    })
  });

  if (!openaiResp.ok) {
    const text = await openaiResp.text();
    return new Response(text, { status: openaiResp.status });
  }
  const json = await openaiResp.json();
  const reply = json.choices?.[0]?.message?.content ?? '';

  return new Response(JSON.stringify({ reply }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
  });
}

