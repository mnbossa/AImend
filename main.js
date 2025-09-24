const sendBtn = document.getElementById('send');
const promptEl = document.getElementById('prompt');
const output = document.getElementById('output');

// Replace with your Worker URL after deployment (no trailing slash required)
const WORKER_URL = 'https://wild-dream-a536.mnbossa.workers.dev';

// The exact HF model ID you tested
const MODEL_ID = 'HuggingFaceTB/SmolLM3-3B:hf-inference';


async function sendPrompt(prompt) {
//const endpoint = new URL('/chat', WORKER_URL).toString();
  const endpoint = `${WORKER_URL}/chat`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000); // 30s timeout

  // Build the chat-completions payload
  const body = {
    model: MODEL_ID,
    messages: [
      { role: 'user', content: prompt }
    ],
    stream: false
  };
  console.log('→ /chat body', body);
  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify( body ),
      signal: controller.signal
    });

    clearTimeout(timeout);

    // Non-2xx: prefer readable text
    if (!resp.ok) {
      const errorBody = await resp.text().catch(()=>'');
      console.error('Worker /chat error', resp.status, errorBody);
      return { ok: false, error: errorBody || `HTTP ${resp.status}`, status: resp.status };
      // const text = await resp.text().catch(() => `HTTP ${resp.status}`);
      // return { ok: false, error: text, status: resp.status };

    }

    let data;
    try {
      data = await resp.json();
    } catch {
      const text = await resp.text().catch(() => '');
      data = { reply: text };
    }

    return { ok: true, data };

    // Try JSON, but gracefully fallback to text
//    try {
//      const data = await resp.json();
//      return { ok: true, data };
//    } catch {
//      const text = await resp.text().catch(() => '');
//      return { ok: true, data: { reply: text } };
//    }
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === 'AbortError') return { ok: false, error: 'Request timed out' };
    return { ok: false, error: err.message || 'Network error' };
  }
}

sendBtn.addEventListener('click', async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) return;
  sendBtn.disabled = true;
  output.textContent = 'Waiting for response...';

  const result = await sendPrompt(prompt);

  sendBtn.disabled = false;

  if (!result.ok) {
    output.textContent = `Error: ${result.error} ${result.status ? `(status ${result.status})` : ''}`;
    return;
  }

//const reply = result.data?.reply ?? 'No reply';
//output.textContent = reply;
  output.textContent = result.data.reply || 'No reply';
});


