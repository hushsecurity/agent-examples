# Hand-off: one agent passes a user on to another

A front agent acting for a signed-in user hands the user off to a specialist
agent, which calls the Hush AI gateway for them. Every step is an RFC 8693
token exchange at Hush, and the specialist's token names the user and both
agents, so the gateway (and its activity log) sees who acted for whom.

```
front agent ──(user's token)──▶ Hush ──▶ front agent's token for the user
front agent ──(that token, resource = specialist)──▶ Hush ──▶ hand-off token
front agent ──(hand-off token)──▶ specialist agent
specialist  ──(hand-off token)──▶ Hush ──▶ specialist's token for the user
specialist  ──(Bearer: that token)──▶ gateway
```

The specialist's token:

```json
{
  "sub": "<the user>",
  "act": { "sub": "<specialist agent id>", "act": { "sub": "<front agent id>" } }
}
```

To keep the example short, both agents run in one script and sign in with a
secret. In practice they're separate services, on any platform: the token
requests stay the same, only how each agent signs in changes (see the other
examples).

## Requirements

- A Hush AI gateway, hosted or on-prem.
- Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The two service agents and their secrets, and a DeepWiki app granted to the specialist |
| [`agent.py`](agent.py) | Both agents: the hand-off, then one DeepWiki call through the gateway as the specialist |
| [`sign_in.py`](sign_in.py) | Signs a user in for the front agent (standard library only) |

## Run it

1. **Register the agents in Hush.** Terraform creates both service agents,
   acting for users, a secret for each, and DeepWiki (a public MCP server that
   needs no sign-in) on your gateway, granted to the specialist.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id>
   ```

2. **Sign in for the front agent** (it opens your browser):

   ```sh
   python sign_in.py https://<gateway>/mcp "$(terraform -chdir=terraform output -raw front_resource)"
   ```

3. **Run it**, right after signing in (a user's token lasts 5 minutes):

   ```sh
   pip install -r requirements.txt
   export HUSH_GATEWAY_URL=https://<gateway>/mcp
   export FRONT_AGENT_ID=$(terraform -chdir=terraform output -raw front_agent_id)
   export FRONT_AGENT_SECRET=$(terraform -chdir=terraform output -raw front_secret)
   export SPECIALIST_AGENT_ID=$(terraform -chdir=terraform output -raw specialist_agent_id)
   export SPECIALIST_AGENT_SECRET=$(terraform -chdir=terraform output -raw specialist_secret)
   export SPECIALIST_RESOURCE=$(terraform -chdir=terraform output -raw specialist_resource)
   python agent.py
   ```

   It prints the specialist's `sub` and `act`, then DeepWiki's answer,
   through the gateway.

## Good to know

- **The front agent names the specialist with its `resource`**: the
  `resource` attribute of `hush_service_agent` (`https://<Hush API>/v1/agents/<agent id>`),
  also shown on the agent's page in the Hush console. The hand-off token works
  only for that agent, and reaches no apps by itself.
- **The specialist must act for users and admit this user** (its `assignment`
  rules; without any, it may act for every user). If it's disabled, or may
  not act for the user, Hush refuses the hand-off and says why.
- **Apps are granted to the agent that calls them**: here only the specialist
  needs DeepWiki. As always when acting for a user, the app must also admit
  that user.
- **A user's identity provider token works too.** When the front agent
  accepts tokens from your identity provider (`user_tokens`, see
  [`agentcore-agent`](../agentcore-agent#or-your-identity-provider-at-the-door)),
  it can hand the user off straight from that token: one exchange instead of
  two. The front agent then signs in with a workload token issued for the
  gateway: a secret doesn't say which gateway the user's token is for.
- **A chain holds at most four agents**, and no agent twice.
- **The hand-off token expires with the user's token**, as every token in the
  chain does.

## Clean up

```sh
terraform -chdir=terraform destroy
```
