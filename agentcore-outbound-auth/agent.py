"""An AgentCore agent whose gateway token comes from AgentCore Identity.

Hush is a credential provider in AgentCore's token vault, and the agent asks
for a token with @requires_access_token: no token code and no secret, since
AgentCore authenticates to Hush with the runtime role's AWS token.

- AUTH_FLOW=ON_BEHALF_OF_TOKEN_EXCHANGE (default): for the user who called
  the runtime. AgentCore exchanges the user's token, checked at the runtime's
  door, for a Hush token naming the user and the agent.
- AUTH_FLOW=M2M: as itself.
"""

import os

from bedrock_agentcore.identity.auth import requires_access_token
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
REGION = os.environ["AWS_REGION"]
MODEL_ID = os.environ["MODEL_ID"]
PROVIDER = os.environ.get("CREDENTIAL_PROVIDER", "hush")
AUTH_FLOW = os.environ.get("AUTH_FLOW", "ON_BEHALF_OF_TOKEN_EXCHANGE")

SYSTEM_PROMPT = """Your tools come through the Hush gateway. hush_list_apps
shows the apps you can use; find an app's tools with hush_search_tools and
run them with hush_call_tool. Keep answers short."""


@requires_access_token(
    provider_name=PROVIDER, auth_flow=AUTH_FLOW, scopes=[], resources=[GATEWAY_URL]
)
def gateway_token(*, access_token: str) -> str:
    return access_token


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    headers = {"Authorization": f"Bearer {gateway_token()}"}
    with MCPClient(url=GATEWAY_URL, headers=headers) as gateway:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
            tools=gateway.list_tools_sync(),
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )
        return str(agent(payload.get("prompt", "Which apps can you use?")))


if __name__ == "__main__":
    app.run()
