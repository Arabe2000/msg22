import asyncio
import json
from aiohttp import web, WSMsgType

PORT = 9090

class SignalingServer:
    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/ws", self.websocket_handler)
        self.rooms = {}  # dicionário: room_id -> lista de websockets

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        room_id = None
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "join":
                        room_id = data.get("room")
                        if not room_id:
                            continue
                        if room_id not in self.rooms:
                            self.rooms[room_id] = []
                        self.rooms[room_id].append(ws)
                    elif room_id and room_id in self.rooms:
                        for peer in self.rooms[room_id]:
                            if peer != ws:
                                await peer.send_str(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    print(f"Erro na conexão WebSocket: {ws.exception()}")
        finally:
            if room_id and ws in self.rooms.get(room_id, []):
                self.rooms[room_id].remove(ws)
                if not self.rooms[room_id]:
                    del self.rooms[room_id]
            await ws.close()

        return ws

    def run(self):
        web.run_app(self.app, port=PORT)

if __name__ == "__main__":
    SignalingServer().run()
