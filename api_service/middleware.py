from __future__ import annotations

import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .encryption import decrypt_payload, derive_key, encrypt_payload

logger = logging.getLogger(__name__)

EXCLUDED_PREFIXES = [
    "/",
    "/health",
    "/token",
    "/docs",
    "/openapi.json",
    "/onboarding",
    "/redoc",
]


class EncryptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _is_excluded(path):
            return await call_next(request)

        jwt = _extract_jwt(request)
        if jwt is not None:
            key = derive_key(jwt)
            body = await request.body()
            if body:
                try:
                    enc = json.loads(body)
                    if isinstance(enc, dict) and "iv" in enc and "data" in enc:
                        plaintext = decrypt_payload(enc, key)
                        plain_bytes = plaintext.encode()

                        async def receive():
                            return {
                                "type": "http.request",
                                "body": plain_bytes,
                                "more_body": False,
                            }

                        request._receive = receive
                except (json.JSONDecodeError, ValueError, Exception) as e:
                    logger.debug("Request decryption failed: %s", e)

        response = await call_next(request)

        if 200 <= response.status_code < 400 and jwt is not None:
            resp_body = b""
            async for chunk in response.body_iterator:
                resp_body += chunk
            if resp_body:
                try:
                    key = derive_key(jwt)
                    enc = encrypt_payload(resp_body.decode(), key)
                    return JSONResponse(content=enc, status_code=response.status_code)
                except Exception as e:
                    logger.debug("Response encryption failed: %s", e)
                    return Response(
                        body=resp_body,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                    )
            return Response(
                body=resp_body,
                status_code=response.status_code,
                headers=dict(response.headers),
            )

        return response


def _is_excluded(path: str) -> bool:
    for prefix in EXCLUDED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    return False


def _extract_jwt(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
