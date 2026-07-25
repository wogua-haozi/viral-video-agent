import re

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from src.api.errors import AppError, app_error_handler
from src.api.routes import router
from src.gateway.model_bootstrap import configure_optional_model_routes

configure_optional_model_routes()

class CandidateDecisionBodyLimitMiddleware:
    def __init__(self, app, maximum: int = 16 * 1024):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not re.fullmatch(r"/jobs/[^/]+/candidates/decisions", scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length", b"")
        if content_length.isdigit() and int(content_length) > self.maximum:
            response = JSONResponse(status_code=413, content={
                "error_code": "REQUEST_BODY_TOO_LARGE",
                "message": "候选确认请求体过大。",
            })
            await response(scope, receive, send)
            return

        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunks.append(message.get("body", b""))
            if sum(len(chunk) for chunk in chunks) > self.maximum:
                response = JSONResponse(status_code=413, content={
                    "error_code": "REQUEST_BODY_TOO_LARGE",
                    "message": "候选确认请求体过大。",
                })
                await response(scope, receive, send)
                return
            more_body = bool(message.get("more_body", False))
        body = b"".join(chunks)
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


app = FastAPI(title="爆款视频分析系统")
app.add_middleware(CandidateDecisionBodyLimitMiddleware)
app.add_exception_handler(AppError, app_error_handler)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
