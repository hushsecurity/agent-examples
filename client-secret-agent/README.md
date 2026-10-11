# Client secret: an agent with no workload identity

An agent that runs where it has no identity of its own (a laptop, a VM, a
vendor's service) signs in to Hush with an id and a secret (OAuth client
credentials), and calls the Hush AI gateway with the Hush token it gets back.
The agent acts as itself.

```
agent ──(agent id + secret)──▶ Hush ──▶ Hush token
agent ──(Bearer: Hush token)──▶ gateway
```

Prefer a workload identity when there is one (see the other examples): there
is no secret to store, leak or rotate.

## Requirements

- A Hush AI gateway, hosted or on-prem.
- Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent and its secret, and a DeepWiki app granted to it |
| [`agent.py`](agent.py) | The agent: signs in with its secret, and makes one DeepWiki call through the gateway with the MCP Python SDK |

## Run it

1. **Register the agent in Hush.** Terraform creates the service agent and a
   secret for it, and DeepWiki (a public MCP server that needs no sign-in) on
   your gateway, granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id>
   ```

2. **Run it.**

   ```sh
   pip install -r requirements.txt
   export HUSH_GATEWAY_URL=https://<gateway>/mcp
   export HUSH_AGENT_ID=$(terraform -chdir=terraform output -raw agent_id)
   export HUSH_AGENT_SECRET=$(terraform -chdir=terraform output -raw secret)
   python agent.py
   ```

   It prints DeepWiki's answer, through the gateway:

   ```
   Available pages for modelcontextprotocol/python-sdk:
   - 1 Overview
   ...
   ```

## Good to know

- **The secret is sent with Basic auth, with the agent's id as the user.**
- **A secret doesn't say which gateway it's for**, so the agent sends
  `resource` (the gateway's issuer, which it discovers from the gateway's URL)
  when it signs in.
- **Keep the secret out of code and images**: in your secret store, or an
  environment variable as here. Terraform keeps it in its state, so protect
  that too.
- **To rotate the secret**, add a second `hush_service_agent_client_secret`,
  move the agent to it, then remove the first: an agent can have two.
- **As itself, the agent can use only apps that need no user's sign-in.**
  Grant it more apps with an assignment rule on `agent.id`.
- **`Hush refused (401)`** means the id or secret is wrong, or the secret was
  removed.

## Clean up

```sh
terraform -chdir=terraform destroy
```
