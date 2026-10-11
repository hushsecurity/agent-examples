"""A Kubernetes agent calling the Hush AI gateway with its service-account token.

The pod sends its projected service-account token as the Bearer, and the
gateway exchanges it with Hush for the agent.
"""

import asyncio
import json
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
TOKEN_FILE = "/var/run/secrets/hush/token"
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-k8s-agent-bearer"


class ServiceAccountToken(httpx2.Auth):
    """Sends the pod's token, read on every request: the kubelet rotates it."""

    def auth_flow(self, request):
        with open(TOKEN_FILE) as f:
            request.headers["Authorization"] = f"Bearer {f.read().strip()}"
        yield request


async def main():
    # Any MCP client works: only the Authorization header is Hush's.
    http = create_mcp_http_client(auth=ServiceAccountToken())
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
