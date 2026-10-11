# Foundry agent: a managed agent, no token code

An [Azure AI Foundry](https://learn.microsoft.com/azure/ai-foundry/agents/)
agent uses the Hush AI gateway as an MCP tool. Foundry runs the agent and
calls the gateway itself, with a token for the agent's own Entra agent
identity; the gateway exchanges it with Hush. There is no token code: only the
agent's definition, and a project connection that tells Foundry how to sign in
to the gateway. The agent acts as itself.

```
Foundry agent ──(Bearer: its agent identity's token)──▶ gateway ──(exchange)──▶ Hush
```

## Requirements

- A Hush AI gateway that Foundry can reach: hosted, or on-prem with a public
  address (`hush-agw` chart 0.7.1 or later).
- A Foundry project with a model deployment. To run `setup.sh`: the Cloud
  Application Administrator role, and permission to add connections to the
  project (e.g. Azure AI Project Manager).
- The Azure CLI, Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`setup.sh`](setup.sh) | The Azure side: the gateway's API in Entra, and the project's connection to the gateway |
| [`agent.py`](agent.py) | The agent's definition (the gateway as an MCP tool), and a way to ask it something |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the agent's identity, and a DeepWiki app granted to it |

## Run it

1. **Connect your Foundry project to the gateway.** It prints the `export`
   lines for the next steps; run them.

   ```sh
   az login --tenant <tenant>
   ./setup.sh <project resource id> https://<gateway>/mcp
   ```

2. **Create the agent.** Foundry gives it its own agent identity, which this
   prints.

   ```sh
   pip install -r requirements.txt
   export FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
   export FOUNDRY_MODEL=<model deployment> HUSH_GATEWAY_URL=https://<gateway>/mcp
   python agent.py create
   ```

3. **Register the agent in Hush.** Terraform creates the service agent, bound
   to that identity, and DeepWiki (a public MCP server that needs no sign-in)
   on your gateway, granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> -var tenant_id=$ENTRA_TENANT_ID \
     -var gateway_api_id=$ENTRA_GATEWAY_API_ID -var agent_identity_id=<agent identity>
   ```

4. **Ask it something.**

   ```sh
   python agent.py ask "Using DeepWiki, list the wiki pages of modelcontextprotocol/python-sdk."
   ```

   ```
   [hush_call_tool] {"name":"custom-deepwiki-foundry-agent_read_wiki_structure",...}
   The wiki pages of modelcontextprotocol/python-sdk are: 1 Overview, 2 FastMCP / MCPServer Framework, ...
   ```

   The same agent is in the Foundry portal too, to chat with in its
   playground.

## Good to know

- **Each Foundry agent has its own agent identity**, so each is a separate
  agent in Hush, with its own apps and its own entries in the gateway's
  activity log.
- **The connection's `audience` is the gateway's API** (`api://<app id>`),
  and the Terraform's `gateway_api_id` must match it. Keep that app for Hush
  only: anything that receives its tokens could replay them.
- **A `401` from the gateway** (in the agent's tool output) usually means the
  agent isn't registered: `agent_identity_id`, `tenant_id` and
  `gateway_api_id` must match. A new agent version keeps its identity.

## Clean up

```sh
terraform -chdir=terraform destroy
```

and delete the agent in the Foundry portal, the `hush-gateway` connection in
the project, and the "Hush gateway (Foundry)" app in Entra.
