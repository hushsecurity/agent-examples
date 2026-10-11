"""An AgentCore agent using the Hush AI gateway as its MCP server.

The agent proves who it is with an AWS token for its runtime's IAM role
(sts:GetWebIdentityToken), and calls the gateway in one of two ways:

- As itself: it sends the AWS token as the Bearer, and the gateway exchanges
  it with Hush.
- For a user ({"user_token": ...} in the payload): it exchanges the AWS token
  and the user's Hush token at Hush for a token naming both, and sends that.
"""

import functools
import os
import time

import boto3
import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
REGION = os.environ["AWS_REGION"]
MODEL_ID = os.environ["MODEL_ID"]

SYSTEM_PROMPT = """Your tools come through the Hush gateway. hush_list_apps
shows the apps you can use; find an app's tools with hush_search_tools and
run them with hush_call_tool. Keep answers short."""


@functools.cache  # once, on first use
def discover() -> tuple[str, str]:
    """The gateway's issuer and Hush's token endpoint, found the standard MCP
    way: the gateway names its issuer, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return issuer, metadata["token_endpoint"]


sts = boto3.client("sts", region_name=REGION, endpoint_url=f"https://sts.{REGION}.amazonaws.com")


def aws_token() -> tuple[str, int]:
    """An AWS-signed token for the runtime's role, issued for the gateway."""
    resp = sts.get_web_identity_token(
        Audience=[discover()[0]], SigningAlgorithm="RS256", DurationSeconds=300
    )
    return resp["WebIdentityToken"], 300


def hush_token_for(user_token: str) -> tuple[str, int]:
    """A Hush token for the agent acting for the user of `user_token`
    (RFC 8693 token exchange; the agent authenticates with its AWS token)."""
    resp = httpx.post(
        discover()[1],
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": aws_token()[0],
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Hush refused ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    return body["access_token"], body["expires_in"]


class Bearer(httpx.Auth):
    """Sends the token `get_token` returns, getting a new one a minute
    before it expires."""

    def __init__(self, get_token):
        self.get_token = get_token
        self.token = None
        self.expires_at = 0.0

    def auth_flow(self, request):
        if time.time() > self.expires_at - 60:
            self.token, expires_in = self.get_token()
            self.expires_at = time.time() + expires_in
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    user_token = payload.get("user_token")
    if user_token:
        auth = Bearer(lambda: hush_token_for(user_token))
    else:
        auth = Bearer(aws_token)

    with MCPClient(url=GATEWAY_URL, auth_provider=auth) as gateway:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
            tools=gateway.list_tools_sync(),
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )
        return str(agent(payload.get("prompt", "Which apps can you use?")))


if __name__ == "__main__":
    app.run()
