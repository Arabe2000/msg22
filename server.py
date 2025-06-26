# server.py
import asyncio
from aiohttp import web
import json

peers = set()

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    peers.add(ws)
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                for peer in peers:
                    if peer != ws:
                        await peer.send_str(msg.data)
    finally:
        peers.discard(ws)

    return ws

app = web.Application()
app.add_routes([web.get('/ws', websocket_handler)])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, port=port)
