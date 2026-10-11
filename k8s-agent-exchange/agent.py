"""A Kubernetes agent exchanging its service-account token for a Hush token.

The agent signs in to Hush itself, with its service-account token as its
client assertion, and calls the Hush AI gateway with the Hush token:

- As itself: OAuth client credentials.
- For a user, when the user's Hush token is mounted: RFC 8693 token exchange,
  which gives a token naming both the user and the agent.
"""

import asyncio
import json
import os
import pathlib
import sys
import time

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
TOKEN_FILE = pathlib.Path("/var/run/secrets/hush/token")
USER_TOKEN_FILE = pathlib.Path("/var/run/secrets/user/token")  # optional
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-k8s-agent-exchange"


def discover() -> tuple[str, str]:
    """The gateway's issuer and Hush's token endpoint, found the standard MCP
    way: the gateway names its issuer, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx2.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx2.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return issuer, metadata["token_endpoint"]


def exchange(endpoint: str) -> dict:
    """Exchanges the pod's token (read fresh: the kubelet rotates it) for a
    Hush token, for the user too when their token is mounted."""
    form = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": TOKEN_FILE.read_text().strip(),
    }
    if USER_TOKEN_FILE.exists():
        form["grant_type"] = "urn:ietf:params:oauth:grant-type:token-exchange"
        form["subject_token"] = USER_TOKEN_FILE.read_text().strip()
        form["subject_token_type"] = "urn:ietf:params:oauth:token-type:access_token"
    resp = httpx2.post(endpoint, data=form)
    if resp.status_code != 200:
        sys.exit(f"Hush refused ({resp.status_code}): {resp.text}")
    return resp.json()


class HushToken(httpx2.Auth):
    """Sends the Hush token, exchanging for a new one a minute before it expires."""

    def __init__(self):
        _, self.endpoint = discover()
        self.renew()  # the first exchange, before connecting

    def renew(self):
        out = exchange(self.endpoint)
        self.token, self.expires_at = out["access_token"], time.time() + out["expires_in"]

    def auth_flow(self, request):
        if time.time() > self.expires_at - 60:
            self.renew()
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


async def main():
    # Any MCP client works: the Hush token is a standard OAuth bearer token.
    http = create_mcp_http_client(auth=HushToken())
    async with http, streamable_http_client(GATEWAY_URL, http_client=http) as (read, write):
        async with ClientSession(read, write) as gateway:
            await gateway.initialize()
            # One call through the gateway: find DeepWiki's tool, then run it.
            found = await gateway.call_tool(
                "hush_search_tools", {"app": DEEPWIKI_APP, "query": "read_wiki_structure"}
            )
            tool = json.loads(found.content[0].text)[0]["name"]
            result = await gateway.call_tool(
                "hush_call_tool",
                {"name": tool, "arguments": {"repoName": "modelcontextprotocol/python-sdk"}},
            )
            print(result.content[0].text[:300])


if __name__ == "__main__":
    asyncio.run(main())
