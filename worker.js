const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type"
};
const JSON_HEADERS = {
  "Content-Type": "application/json; charset=UTF-8",
  ...CORS_HEADERS
};

export default {
  async fetch(request, env) {
    // 1. Preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // 2. Only POST /chat
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/chat") {
      return new Response(
        JSON.stringify({ error: "Only POST /chat supported" }),
        { status: 405, headers: JSON_HEADERS }
      );
    }

    // 3. Parse incoming JSON
    let payload;
    try {
      payload = await request.json();
    } catch {
      return new Response(
        JSON.stringify({ error: "Invalid JSON body" }),
        { status: 400, headers: JSON_HEADERS }
      );
    }

    // 4. Ensure we have messages
    if (!Array.isArray(payload.messages) || payload.messages.length === 0) {
      return new Response(
        JSON.stringify({ error: "Missing messages array" }),
        { status: 400, headers: JSON_HEADERS }
      );
    }

    // 5. Read HF token from your Worker secret
    const hfToken = env.SECRET_HF_TOKEN;
    if (!hfToken) {
      return new Response(
        JSON.stringify({ error: "Hugging Face token not configured" }),
        { status: 500, headers: JSON_HEADERS }
      );
    }

    // 6. Proxy to HF chat-completions router
    const hfResponse = await fetch(
      "https://router.huggingface.co/v1/chat/completions",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${hfToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: payload.model,
          messages: payload.messages,
          stream: payload.stream ?? false
        })
      }
    );

    const hfData = await hfResponse.json();

    // 7. Forward errors verbatim
    if (!hfResponse.ok) {
      return new Response(JSON.stringify(hfData), {
        status: hfResponse.status,
        headers: JSON_HEADERS
      });
    }

    // 8. Extract assistant reply
//  const reply =
//    hfData.choices?.[0]?.message?.content ?? JSON.stringify(hfData);
    // 8. Extract assistant reply, trimming off any <think>…</think> block
    let content = hfData.choices?.[0]?.message?.content ?? "";
    const marker = "</think>";
    const idx = content.indexOf(marker);
    const reply = idx >= 0
      ? content.slice(idx + marker.length).trim()
      : content;


    return new Response(JSON.stringify({ reply }), {
      status: 200,
      headers: JSON_HEADERS
    });
  }
};



/*
    const OPENAI_API_KEY = env.SECRET_OPENAI_API_KEY;
    if (!OPENAI_API_KEY) return makeCorsResponse('OpenAI key missing', 500);

    try {
      const openaiResp = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${OPENAI_API_KEY}`
        },
        body: JSON.stringify({
          model: 'gpt-3.5-turbo',
          messages: [{ role: 'user', content: prompt }],
          max_tokens: 800
        })
      });

      const text = await openaiResp.text();
      const status = openaiResp.status;
      const contentType = openaiResp.headers.get('content-type') || 'text/plain';

      return new Response(text, {
        status,
        headers: {
          'Content-Type': contentType,
          'Access-Control-Allow-Origin': '*'
        }
      });
    } catch (err) {
      return makeCorsResponse('Upstream request failed', 502);
    }
*/