"""An Azure agent calling the Hush AI gateway with its managed identity.

The agent asks Azure for a token for the gateway's API, as its managed
identity, and sends it as the Bearer: the gateway exchanges it with Hush. It
runs on any Azure compute with a managed identity (a VM, Container Apps,
Container Instances, App Service, Functions).
"""

import asyncio
import json
import os

import httpx2
from azure.identity import ManagedIdentityCredential
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
GATEWAY_API_ID = os.environ["ENTRA_GATEWAY_API_ID"]  # the gateway's API (app id)
IDENTITY_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")  # which managed identity, if several
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-azure-managed-identity"


class ManagedIdentityToken(httpx2.Auth):
    """Sends a token for the gateway's API, as the managed identity. Azure
    caches it and gets a new one before it expires."""

    credential = ManagedIdentityCredential(client_id=IDENTITY_CLIENT_ID)

    def auth_flow(self, request):
        token = self.credential.get_token(f"api://{GATEWAY_API_ID}/.default").token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


async def main():
    # Any MCP client works: only the Authorization header is Hush's.
    http = create_mcp_http_client(auth=ManagedIdentityToken())
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
