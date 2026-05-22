from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from .encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

UNENCRYPTED_PATHS = {
    "/",
    "/health",
    "/onboarding/passkey",
    "/onboarding/passkey.qr",
}


class CryptoMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if path in UNENCRYPTED_PATHS:
            return await call_next(request)

        config_mgr = request.app.state.config_mgr
        enc_key = config_mgr.get_config("encryption_key")

        if not enc_key:
            return await call_next(request)

        if request.method in ("POST", "PUT", "DELETE"):
            body = await request.body()
            if body:
                try:
                    payload = json.loads(body)
                    plaintext = decrypt(payload, enc_key)
                    inner = json.loads(plaintext)

                    auth_token = inner.get("_token")
                    if auth_token:
                        request.state.auth_token = auth_token

                    inner_body = inner.get("_body", {})
                    request._body = json.dumps(inner_body).encode()
                except Exception as e:
                    logger.warning("Failed to decrypt request body: %s", e)

        response = await call_next(request)

        body_parts = [chunk async for chunk in response.body_iterator]
        body = b"".join(body_parts)

        if body:
            try:
                encrypted = encrypt(body.decode("utf-8"), enc_key)
                resp_headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() != "content-length"
                }
                return StarletteResponse(
                    content=json.dumps(encrypted),
                    status_code=response.status_code,
                    headers=resp_headers,
                    media_type="application/json",
                )
            except Exception as e:
                logger.warning("Failed to encrypt response body: %s", e)

        return response
