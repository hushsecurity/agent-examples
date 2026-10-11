"""An agent with no workload identity, calling the Hush AI gateway with a secret.

The agent signs in to Hush with its id and secret (OAuth client credentials),
and calls the gateway with the Hush token it gets back. It runs anywhere: a
laptop, a VM, or a service that can't get a workload token.
"""

import asyncio
import json
import os
import sys
import time

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
AGENT_ID = os.environ["HUSH_AGENT_ID"]
AGENT_SECRET = os.environ["HUSH_AGENT_SECRET"]
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-client-secret-agent"


def discover() -> tuple[str, str]:
    """The gateway's issuer and Hush's token endpoint, found the standard MCP
    way: the gateway names its issuer, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx2.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx2.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return issuer, metadata["token_endpoint"]


class HushToken(httpx2.Auth):
    """Sends the agent's Hush token, signing in again a minute before it expires."""

    def __init__(self):
        self.issuer, self.endpoint = discover()
        self.renew()  # the first sign-in, before connecting

    def renew(self):
        resp = httpx2.post(
            self.endpoint,
            auth=(AGENT_ID, AGENT_SECRET),  # Basic auth: the agent's id and secret
            # A secret doesn't say which gateway it's for: `resource` does.
            data={"grant_type": "client_credentials", "resource": self.issuer},
        )
        if resp.status_code != 200:
            sys.exit(f"Hush refused ({resp.status_code}): {resp.text}")
        out = resp.json()
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
