import os

import socketio


socket_manager = None
if os.getenv("TESTING") != "True":
    socket_manager = socketio.AsyncAioPikaManager(
        os.getenv("RABBITMQ_SOCKETIO_URL")
        or os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    )

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    client_manager=socket_manager,
)


@sio.event
async def connect(sid, environ, auth):

    if auth and "user_id" in auth:
        user_id = auth["user_id"]
        await sio.enter_room(sid, f"user_{user_id}")
        print(f"User {user_id} connected to sockets (sid: {sid})")
    else:
        print(f"Connection without user_id (sid: {sid})")


@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
