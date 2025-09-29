# handler.py
import os
import json
import httpx

async def handle_chat(payload: dict):
    # forward envelope signing logic could live here, but keep imports local to runtime
    res = await httpx.AsyncClient().post(
        f"{os.environ.get('WORKER_URL').rstrip('/')}/chat",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    return res.json()
