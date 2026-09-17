"""Bound HTTP request streams, including requests without Content-Length."""

from starlette.exceptions import HTTPException


class BodyLimit:
    def __init__(self, app, maximum=22 * 1024 * 1024):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.maximum:
                    raise HTTPException(413, "요청은 22MB 이하여야 합니다.")
            return message

        await self.app(scope, bounded_receive, send)
