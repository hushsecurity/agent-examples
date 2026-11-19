"""Your API, checking the Hush tokens agents call it with: GET /orders on
http://localhost:8000.

In production, your API gateway usually does these checks (JWT / OpenID
Connect validation), with no code.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx2
import jwt

# Pin your own deployments' issuers: Hush signs every organization's tokens
# with the same keys, so the issuer is what ties a token to yours.
ISSUER = os.environ["HUSH_ISSUER"]
AUDIENCE = os.environ["API_AUDIENCE"]
SCOPE = "orders:read"

metadata = httpx2.get(f"{ISSUER}/.well-known/oauth-authorization-server").raise_for_status().json()
keys = jwt.PyJWKClient(metadata["jwks_uri"])


def verify(authorization: str) -> dict:
    """The claims of a valid Hush token for this API; raises otherwise."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise jwt.InvalidTokenError("no bearer token")
    return jwt.decode(
        token,
        keys.get_signing_key_from_jwt(token).key,
        algorithms=["RS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["iss", "aud", "exp", "sub"]},
    )


class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/orders":
            return self.reply(404, {"error": "not found"})
        try:
            claims = verify(self.headers.get("Authorization", ""))
        except jwt.InvalidTokenError as e:
            return self.reply(401, {"error": str(e)})
        if SCOPE not in claims.get("scope", "").split():
            return self.reply(403, {"error": f"needs scope {SCOPE}"})
        # The user (sub), and the agent acting for them (act).
        self.reply(200, {"user": claims["sub"], "agent": claims.get("act", {}).get("sub"), "orders": []})

    def reply(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


if __name__ == "__main__":
    print("Serving http://localhost:8000/orders")
    HTTPServer(("localhost", 8000), Api).serve_forever()
