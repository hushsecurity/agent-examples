"""An agent calling your own API for a user, with a Hush token for that API.

The agent exchanges the user's token at Hush (RFC 8693 token exchange) for a
token for your API: `resource` is the API's audience, and `scope` what the
agent needs. The token names the user, and the agent in `act`. Your API
(api.py) checks it.
"""

import os
import sys

import httpx2

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
AGENT_ID = os.environ["HUSH_AGENT_ID"]
AGENT_SECRET = os.environ["HUSH_AGENT_SECRET"]
API_AUDIENCE = os.environ["API_AUDIENCE"]
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def token_endpoint() -> str:
    """Hush's token endpoint, found the standard MCP way: the gateway names
    its issuer, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx2.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx2.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return metadata["token_endpoint"]


def api_token(user_token: str) -> str:
    """A token for the API, for the agent acting for the user of `user_token`."""
    resp = httpx2.post(
        token_endpoint(),
        auth=(AGENT_ID, AGENT_SECRET),  # Basic auth: the agent's id and secret
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "resource": API_AUDIENCE,
            "scope": "orders:read",
        },
    )
    if resp.status_code != 200:
        sys.exit(f"Hush refused ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def main():
    with open(".user-token") as f:
        user_token = f.read().strip()
    token = api_token(user_token)
    resp = httpx2.get(f"{API_URL}/orders", headers={"Authorization": f"Bearer {token}"})
    print(resp.status_code, resp.text)


if __name__ == "__main__":
    main()
