# --- Servidor de Sinalização 20M Shield Melhorado ---

import asyncio
import json
import logging
import time
from aiohttp import web, WSMsgType
from aiohttp.web_ws import WSMsgType

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get('PORT', 9090))

class SignalingServer:
    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/ws", self.websocket_handler)
        self.app.router.add_get("/", self.health_check)
        self.app.router.add_get("/health", self.health_check)
        
        # Estruturas de dados para salas
        self.rooms = {}  # room_id -> {'clients': [ws], 'created': timestamp}
        self.client_rooms = {}  # ws -> room_id
        
        # Limpar salas vazias periodicamente
        asyncio.create_task(self.cleanup_empty_rooms())

    async def health_check(self, request):
        """Endpoint de health check para o Render"""
        return web.json_response({
            'status': 'healthy',
            'rooms': len(self.rooms),
            'total_clients': sum(len(room['clients']) for room in self.rooms.values())
        })

    async def cleanup_empty_rooms(self):
        """Remove salas vazias periodicamente"""
        while True:
            try:
                await asyncio.sleep(300)  # Executar a cada 5 minutos
                current_time = time.time()
                empty_rooms = []
                
                for room_id, room_data in self.rooms.items():
                    # Remover conexões fechadas
                    room_data['clients'] = [ws for ws in room_data['clients'] 
                                          if not ws.closed]
                    
                    # Marcar salas vazias para remoção
                    if not room_data['clients']:
                        empty_rooms.append(room_id)
                
                # Remover salas vazias
                for room_id in empty_rooms:
                    del self.rooms[room_id]
                    logger.info(f"Sala vazia removida: {room_id}")
                    
            except Exception as e:
                logger.error(f"Erro na limpeza de salas: {e}")

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=30)  # Heartbeat de 30s
        await ws.prepare(request)
        
        room_id = None
        client_id = id(ws)
        
        logger.info(f"Nova conexão WebSocket: {client_id}")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_message(ws, data, client_id)
                        
                        # Atualizar room_id se cliente entrou em sala
                        if data.get("type") == "join":
                            room_id = data.get("room")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"Mensagem JSON inválida de {client_id}")
                        await ws.send_str(json.dumps({
                            "type": "error",
                            "message": "Formato JSON inválido"
                        }))
                    except Exception as e:
                        logger.error(f"Erro ao processar mensagem de {client_id}: {e}")
                        
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"Erro na conexão WebSocket {client_id}: {ws.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSE:
                    logger.info(f"Conexão WebSocket {client_id} fechada normalmente")
                    break
                    
        except asyncio.CancelledError:
            logger.info(f"Conexão {client_id} cancelada")
        except Exception as e:
            logger.error(f"Erro inesperado na conexão {client_id}: {e}")
        finally:
            await self.cleanup_client(ws, room_id, client_id)

        return ws

    async def handle_message(self, ws, data, client_id):
        msg_type = data.get("type")
        
        if msg_type == "join":
            await self.handle_join(ws, data, client_id)
        elif msg_type in ["offer", "answer", "ice-candidate"]:
            await self.handle_signaling(ws, data, client_id)
        else:
            logger.warning(f"Tipo de mensagem desconhecido de {client_id}: {msg_type}")

    async def handle_join(self, ws, data, client_id):
        room_id = data.get("room")
        if not room_id:
            await ws.send_str(json.dumps({
                "type": "error",
                "message": "ID da sala é obrigatório"
            }))
            return
        
        # Remover cliente de sala anterior se existir
        if ws in self.client_rooms:
            old_room = self.client_rooms[ws]
            if old_room in self.rooms and ws in self.rooms[old_room]['clients']:
                self.rooms[old_room]['clients'].remove(ws)
        
        # Criar sala se não existir
        if room_id not in self.rooms:
            self.rooms[room_id] = {
                'clients': [],
                'created': time.time()
            }
            logger.info(f"Nova sala criada: {room_id}")
        
        # Adicionar cliente à sala
        self.rooms[room_id]['clients'].append(ws)
        self.client_rooms[ws] = room_id
        
        client_count = len(self.rooms[room_id]['clients'])
        logger.info(f"Cliente {client_id} entrou na sala {room_id} ({client_count} clientes)")
        
        # Confirmar entrada na sala
        await ws.send_str(json.dumps({
            "type": "joined",
            "room": room_id,
            "clients": client_count
        }))

    async def handle_signaling(self, ws, data, client_id):
        room_id = self.client_rooms.get(ws)
        if not room_id or room_id not in self.rooms:
            await ws.send_str(json.dumps({
                "type": "error",
                "message": "Cliente não está em uma sala válida"
            }))
            return
        
        # Encaminhar mensagem para outros clientes na sala
        room_clients = self.rooms[room_id]['clients']
        message = json.dumps(data)
        
        forwarded_count = 0
        for peer in room_clients:
            if peer != ws and not peer.closed:
                try:
                    await peer.send_str(message)
                    forwarded_count += 1
                except Exception as e:
                    logger.warning(f"Erro ao encaminhar mensagem para peer: {e}")
        
        logger.debug(f"Mensagem {data.get('type')} encaminhada para {forwarded_count} peers na sala {room_id}")

    async def cleanup_client(self, ws, room_id, client_id):
        """Limpa recursos quando cliente desconecta"""
        try:
            # Remover da sala
            if room_id and room_id in self.rooms:
                if ws in self.rooms[room_id]['clients']:
                    self.rooms[room_id]['clients'].remove(ws)
                    logger.info(f"Cliente {client_id} removido da sala {room_id}")
                
                # Remover sala se vazia
                if not self.rooms[room_id]['clients']:
                    del self.rooms[room_id]
                    logger.info(f"Sala vazia removida: {room_id}")
            
            # Remover do mapeamento de clientes
            if ws in self.client_rooms:
                del self.client_rooms[ws]
            
            # Fechar WebSocket se ainda aberto
            if not ws.closed:
                await ws.close()
                
        except Exception as e:
            logger.error(f"Erro na limpeza do cliente {client_id}: {e}")

def create_app():
    server = SignalingServer()
    return server.app

def main():
    server = SignalingServer()
    
    logger.info(f"Iniciando servidor de sinalização na porta {PORT}")
    web.run_app(server.app, host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    import os
    main()