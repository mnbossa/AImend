import crypto from "crypto";
import fetch from "node-fetch";

function makeEnvelope(payload) {
  const ts = Math.floor(Date.now() / 1000);
  const nonce = crypto.randomBytes(8).toString("hex");
  return { ...payload, timestamp: ts, nonce };
}

function signPayload(envelope, secret) {
  const raw = JSON.stringify(envelope);
  return "sha256=" + crypto.createHmac("sha256", secret).update(Buffer.from(raw, "utf8")).digest("hex");
}

async function forwardToWorker(payload) {
  const envelope = makeEnvelope(payload);
  const sig = signPayload(envelope, process.env.WORKER_SHARED_SECRET);
  const res = await fetch(`${process.env.WORKER_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Signature": sig
    },
    body: JSON.stringify(envelope)
  });
  return res.json();
}
