// worker.js
// Expects these bindings added to the Worker in Cloudflare:
// - SECRET_HF_TOKEN      (secret)
// - WORKER_SHARED_SECRET (secret)
// - ALLOWED_ORIGIN       (plain env, optional)

const MAX_BODY_BYTES = 64 * 1024;

export default {
  async fetch(request, env, ctx) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }

    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/chat") {
      return jsonResponse({ error: "Only POST /chat supported" }, 404, env);
    }

    // Read raw body bytes
    let rawUint8;
    try {
      rawUint8 = await readRawBody(request, MAX_BODY_BYTES);
    } catch (e) {
      return jsonResponse({ error: "Request body too large or unreadable" }, 413, env);
    }

    // Validate signature & freshness (returns parsed payload on success)
    const verified = await validateSignatureAndFreshness(request, rawUint8, env);
    if (!verified.ok) {
      return jsonResponse({ error: verified.reason || "Unauthorized" }, verified.code || 401, env);
    }
    const payload = verified.payload;

    if (!Array.isArray(payload.messages) || payload.messages.length === 0) {
      return jsonResponse({ error: "Missing messages array" }, 400, env);
    }

    const hfToken = env.SECRET_HF_TOKEN;
    if (!hfToken) {
      return jsonResponse({ error: "Hugging Face token not configured" }, 500, env);
    }

    // Minimal model name sanity
    if (typeof payload.model === "string" && payload.model.length > 200) {
      return jsonResponse({ error: "Model identifier too long" }, 400, env);
    }

    try {
      const hfResp = await fetch("https://router.huggingface.co/v1/chat/completions", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${hfToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: payload.model,
          messages: payload.messages,
          stream: payload.stream ?? false
        })
      });

      const text = await hfResp.text();
      let body;
      try { body = JSON.parse(text); } catch { body = { reply: text }; }

      if (!hfResp.ok) {
        return jsonResponse(body, hfResp.status, env);
      }

      const assistantContent = body.choices?.[0]?.message?.content ?? "";
      const marker = "</think>";
      const idx = assistantContent.indexOf(marker);
      const reply = idx >= 0 ? assistantContent.slice(idx + marker.length).trim() : assistantContent;

      return jsonResponse({ reply, raw: body }, 200, env);
    } catch (err) {
      return jsonResponse({ error: "Upstream request failed", message: String(err) }, 502, env);
    }
  }
};

/* Helpers */

function corsHeaders(env) {
  const allowed = env.ALLOWED_ORIGIN || "*";
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Signature",
    "Access-Control-Max-Age": "600"
  };
}

function jsonResponse(obj, status = 200, env = {}) {
  const headers = { ...corsHeaders(env), "Content-Type": "application/json; charset=UTF-8" };
  return new Response(JSON.stringify(obj), { status, headers });
}

async function readRawBody(request, maxBytes) {
  const buffer = await request.arrayBuffer();
  if (buffer.byteLength > maxBytes) throw new Error("body too large");
  return new Uint8Array(buffer);
}

function arrayBufferToHex(buffer) {
  const bytes = new Uint8Array(buffer);
  let hex = "";
  for (let b of bytes) hex += b.toString(16).padStart(2, "0");
  return hex;
}

function constantTimeEq(a, b) {
  if (a.length !== b.length) return false;
  let v = 0;
  for (let i = 0; i < a.length; i++) v |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return v === 0;
}

async function validateSignatureAndFreshness(request, rawUint8, env) {
  const sigHeader = request.headers.get("X-Signature") || "";
  if (!sigHeader.startsWith("sha256=")) return { ok: false, code: 401, reason: "Missing or malformed X-Signature" };
  const sentHex = sigHeader.slice(7);

  const secret = env.WORKER_SHARED_SECRET;
  if (!secret) return { ok: false, code: 500, reason: "Shared secret not configured" };

  // Import key and compute HMAC over raw bytes
  const keyBytes = new TextEncoder().encode(secret);
  let cryptoKey;
  try {
    cryptoKey = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  } catch (e) {
    return { ok: false, code: 500, reason: "Crypto importKey failed" };
  }

  let sigBuf;
  try {
    sigBuf = await crypto.subtle.sign({ name: "HMAC", hash: "SHA-256" }, cryptoKey, rawUint8);
  } catch (e) {
    return { ok: false, code: 500, reason: "Crypto sign failed" };
  }

  const expectedHex = arrayBufferToHex(sigBuf);
  if (!constantTimeEq(expectedHex, sentHex)) return { ok: false, code: 401, reason: "Invalid signature" };

  // Parse JSON and check timestamp window & nonce presence
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(rawUint8));
  } catch {
    return { ok: false, code: 400, reason: "Invalid JSON" };
  }

  const ts = Number(payload.timestamp || 0);
  const now = Math.floor(Date.now() / 1000);
  const WINDOW = 120;
  if (!ts || Math.abs(now - ts) > WINDOW) return { ok: false, code: 400, reason: "Timestamp out of window" };

  // Optional: check payload.nonce uniqueness using durable store (not included here)
  return { ok: true, payload };
}
