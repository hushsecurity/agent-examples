# Demo: chat with agents through the Hush AI gateway

A small web app to try the Hush AI gateway with real LLM agents. Chat with an
agent on **Amazon Bedrock AgentCore** or **Azure AI Foundry**, switch between
the agent acting **as itself** and acting **for you**, and watch what the
gateway sees and does:

- **What the gateway sees**: the agent alone, or you with the agent acting
  for you.
- **Tool calls**: each call the agent made through the gateway in the last
  turn, and how it ended.
- **Gateway activity**: the gateway's audit log for the demo's apps.

The agents use two apps that need nothing outside Hush:

- **DeepWiki**, a public MCP server that needs no sign-in: the agents can use
  it as themselves.
- **Hush's own MCP server**, which each user connects with their own Hush
  sign-in: the agents can use it only for a user, and then as that user. The
  gateway allows its read tools, asks the user before a write, and blocks the
  destructive ones.

## Scenarios

The app suggests these; each is one click.

| Scenario | What to look for |
| -------- | ---------------- |
| Which apps can you use? | As itself, the agent gets its own apps; for you, it gets yours. |
| Ask DeepWiki | Works as itself: DeepWiki needs no sign-in. |
| Recent gateway decisions | The Hush app is per user. As itself the agent can't use it; for you, the first time it gives you a link to connect, then it works as you. |
| Create a tag | A write: the gateway holds the call until you approve it (through your gateway's consent methods: a Slack message or a browser sign-in). |
| Delete a campaign | A destructive tool: the gateway blocks it, whoever asks. |

## How the agents connect

| | As itself | For you |
| - | --------- | ------- |
| **AgentCore** | Sends its runtime role's AWS token as the Bearer ([`agentcore-agent`](../agentcore-agent)) | Exchanges the AWS token and your Hush token at Hush for a token naming both; the app keeps you signed in to Hush and hands the agent a fresh token each turn |
| **Foundry** | Foundry sends the agent identity's token as the Bearer ([`foundry-agent`](../foundry-agent)) | Foundry signs you in to the gateway once (OAuth identity passthrough) and calls it with your own Hush token |

## Requirements

- A Hush AI gateway that AgentCore and Foundry can reach (hosted, or on-prem
  with a public address and the `hush-agw` chart 0.7.1 or later), in the US
  realm.
- A Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)).
- AWS: an account with outbound identity federation enabled
  (`aws iam enable-outbound-web-identity-federation`), and the AgentCore
  starter toolkit (`pip install bedrock-agentcore-starter-toolkit`).
- Azure: a Foundry project with a deployment of a capable model (e.g.
  gpt-5.4: Foundry ends a turn when a tool call fails, so a small model that
  guesses tool names gets stuck), the Cloud Application Administrator role,
  and permission to add connections to the project.
- The Azure CLI signed in as the person running the demo, in the Foundry
  project's tenant, with at least the Foundry Agent Consumer role: the app
  calls Foundry as you.
- Terraform, Python 3.10+, curl and jq.

## Files

| File | What it is |
| ---- | ---------- |
| [`agentcore/agent.py`](agentcore/agent.py) | The AgentCore agent (Strands), reporting its tool calls and the identity it used |
| [`foundry/setup.sh`](foundry/setup.sh) | The Foundry project's two connections to the gateway, and the gateway's API in Entra |
| [`foundry/agents.py`](foundry/agents.py) | The two Foundry agents, one per connection |
| [`terraform/main.tf`](terraform/main.tf) | The two service agents, and the DeepWiki and Hush apps with their access rules |
| [`app/`](app) | The web app: `server.py` (FastAPI) and `index.html` |

## Run it

1. **Deploy the AgentCore agent.**

   ```sh
   cd agentcore
   agentcore configure --entrypoint agent.py --name hush_demo_agent \
     --region us-east-1 --requirements-file requirements.txt --disable-memory --non-interactive
   agentcore deploy -a hush_demo_agent \
     --env HUSH_GATEWAY_URL=https://<gateway>/mcp --env MODEL_ID=us.anthropic.claude-sonnet-5
   export TF_VAR_agentcore_role_arn=$(python3 -c "import yaml; print(yaml.safe_load(open('.bedrock_agentcore.yaml'))['agents']['hush_demo_agent']['aws']['execution_role'])")
   export AGENTCORE_RUNTIME_ARN=$(python3 -c "import yaml; print(yaml.safe_load(open('.bedrock_agentcore.yaml'))['agents']['hush_demo_agent']['bedrock_agentcore']['agent_arn'])")
   cd ..
   ```

2. **Set up the Foundry agents.** Each step prints `export` lines for
   Terraform; run them.

   ```sh
   az login --tenant <tenant>
   ./foundry/setup.sh <project resource id> https://<gateway>/mcp
   pip install -r foundry/requirements.txt
   export FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
   export FOUNDRY_MODEL=<model deployment> HUSH_GATEWAY_URL=https://<gateway>/mcp
   python foundry/agents.py
   ```

3. **Set up Hush.** Terraform creates the two service agents and the two apps
   on your gateway. `users` are the people who will try the demo: the apps are
   granted to them when an agent acts for them.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> \
     -var 'users=["you@example.com"]' \
     -var aws_issuer="$(aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text)"
   export AGENTCORE_RESOURCE=$(terraform -chdir=terraform output -raw agentcore_resource)
   ```

4. **Run the app**, and open http://localhost:8765.

   ```sh
   pip install -r app/requirements.txt
   cd app && uvicorn server:app --port 8765
   ```

   The app needs `HUSH_GATEWAY_URL`, `AGENTCORE_RUNTIME_ARN`,
   `AGENTCORE_RESOURCE`, `FOUNDRY_PROJECT_ENDPOINT` and the API key
   (`HUSH_API_KEY_ID`, `HUSH_API_KEY_SECRET`, to read the activity log), all
   set by the steps above, and AWS credentials that can invoke the AgentCore
   runtime. On another port, set `DEMO_PORT` too.

## Good to know

- **AgentCore "for you"**: sign in to Hush with the button at the top. A
  user's Hush token lasts minutes, so the app refreshes it and hands the agent
  a fresh one each turn.
- **Foundry "for you"**: the first time, the reply has a "Sign in to the
  gateway" button: Foundry signs you in to the gateway once, then the agent
  calls it as you. The gateway sees you, signed in through Foundry; Foundry
  doesn't pass the agent's identity along with yours.
- **Foundry ends a turn when a tool call fails**, including when the gateway
  blocks a call or asks for consent. For consent, the app then asks the agent
  to request it, so you still get the approval link. An approval takes effect
  with the agent's next token, which Foundry doesn't fetch mid-session: try
  the approved call with AgentCore.
- **The activity log can lag the gateway by several minutes**; the tool calls
  panel shows each call at once.
- **The demo is for one person at a time**, on their own machine: it keeps one
  sign-in, and calls Foundry with your Azure CLI sign-in.

## Clean up

```sh
terraform -chdir=terraform destroy
(cd agentcore && agentcore destroy -a hush_demo_agent)
```

and delete the two Foundry agents (`hush-demo-as-agent`, `hush-demo-for-user`)
and the project's `hush-demo-agent` and `hush-demo-user` connections in the
Foundry portal, and the "Hush gateway (demo)" app in Entra.
