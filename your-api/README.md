# Your API: an agent calls your own API for a user

Not every service an agent calls is an MCP server behind the Hush AI gateway.
For your own APIs, Hush issues the agent a standard OAuth token for the API
(a resource server), and your API, or the API gateway in front of it, checks
it. You decide in Hush which agents and users get tokens for it, and with
which scopes.

```
agent ──(user's token, resource = your API, scope)──▶ Hush ──▶ token for your API
agent ──(Bearer: that token)──▶ your API: checks iss, aud, exp, scope; reads sub and act
```

The token names the user and the agent acting for them:

```json
{
  "iss": "https://<Hush API>/v1/deployments/<deployment id>/agents",
  "aud": "https://api.example.com/orders",
  "sub": "<the user>",
  "act": { "sub": "<agent id>" },
  "scope": "orders:read"
}
```

## Requirements

- A Hush AI gateway, hosted or on-prem (users sign in through it).
- Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent and its secret, your API as a resource server, and who gets tokens for it |
| [`agent.py`](agent.py) | The agent: gets a token for the API for the user, and calls it |
| [`api.py`](api.py) | Your API: checks the token, and answers with the user and the agent |
| [`sign_in.py`](sign_in.py) | Signs a user in for the agent (standard library only) |

## Run it

1. **Register the agent and your API in Hush.** Terraform creates the service
   agent, acting for users, and its secret; the API as a resource server with
   two scopes; and a resource application granting the agent `orders:read`
   for every user.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id>
   ```

2. **Start the API**, in another terminal:

   ```sh
   pip install -r requirements.txt
   export HUSH_ISSUER=$(terraform -chdir=terraform output -raw issuer)
   export API_AUDIENCE=$(terraform -chdir=terraform output -raw api_audience)
   python api.py
   ```

3. **Sign in for the agent** (it opens your browser), and run it right after
   (a user's token lasts 5 minutes):

   ```sh
   python sign_in.py https://<gateway>/mcp "$(terraform -chdir=terraform output -raw resource)"
   export HUSH_GATEWAY_URL=https://<gateway>/mcp
   export HUSH_AGENT_ID=$(terraform -chdir=terraform output -raw agent_id)
   export HUSH_AGENT_SECRET=$(terraform -chdir=terraform output -raw secret)
   export API_AUDIENCE=$(terraform -chdir=terraform output -raw api_audience)
   python agent.py
   ```

   It prints your API's answer:

   ```
   200 {"user": "<the user>", "agent": "<agent id>", "orders": []}
   ```

## Good to know

- **Your API must pin the issuer**: Hush signs every organization's tokens
  with the same keys, and the audience is unique only within your
  organization. Accept only your own deployments' issuers.
- **Check `aud`, `exp` and `scope` too.** Tokens can't be revoked, so their
  lifetime (`token_lifetime` on the resource server, 1 hour by default) is
  what ends access.
- **Most API gateways can do the checks with configuration only** (JWT or
  OpenID Connect validation): the issuer's discovery document is at
  `<issuer>/.well-known/openid-configuration`.
- **Asking for a scope the agent isn't granted fails** at Hush. Without
  `scope`, the token carries every scope granted.
- **Acting for a user, both the user and the agent must be granted** the
  resource application. Add user properties to its `assignment` rules (such
  as `groups`) to narrow it.
- **As itself, the agent gets a token for the API the same way** with
  client credentials, signing in with a workload identity issued for the
  gateway (see the other examples): a secret doesn't say which gateway it's
  for.
- **Add claims from the user's profile** to the tokens with `token_claim` on
  the resource server, when your API needs more than who the user is.

## Clean up

```sh
terraform -chdir=terraform destroy
```
