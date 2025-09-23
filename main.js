const sendBtn = document.getElementById('send');
const promptEl = document.getElementById('prompt');
const output = document.getElementById('output');

// Replace with your Worker URL after deployment
const WORKER_URL = 'https://wild-dream-a536.mnbossa.workers.dev';

sendBtn.addEventListener('click', async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) return;
  output.textContent = 'Waiting for response...';
  try {
    const resp = await fetch(WORKER_URL + '/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    if (!resp.ok) {
      const txt = await resp.text();
      output.textContent = 'Error: ' + txt;
      return;
    }
    const data = await resp.json();
    output.textContent = data.reply ?? 'No reply';
  } catch (err) {
    output.textContent = 'Network error: ' + err.message;
  }
});

