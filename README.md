# Hush agent examples

Example agents that connect to the [Hush](https://hush.security) AI gateway
with their own identity: the identity of the workload they run on, instead of
a person's sign-in or a static secret.

Each folder is one self-contained use case, with the Terraform for the Hush
side, the platform side and the agent's code.

| Example | The agent runs on | How it connects | Acts for a user |
| ------- | ----------------- | --------------- | --------------- |
| [`k8s-agent-bearer`](k8s-agent-bearer) | Kubernetes | Sends its service-account token as the Bearer | |
| [`k8s-agent-exchange`](k8s-agent-exchange) | Kubernetes | Exchanges its service-account token for a Hush token | ✓ Token exchange |
| [`entra-agent`](entra-agent) | Anywhere (an Entra agent identity) | Sends its Entra token as the Bearer | ✓ Entra on-behalf-of token |
| [`foundry-agent`](foundry-agent) | Azure AI Foundry (managed) | Foundry sends the agent identity's token as the Bearer, with no token code | |
| [`azure-managed-identity`](azure-managed-identity) | Azure compute (VM, Container Apps, …) | Sends its managed identity's token as the Bearer | |
| [`agentcore-agent`](agentcore-agent) | Amazon Bedrock AgentCore | Sends its AWS token as the Bearer | ✓ Token exchange |
| [`client-secret-agent`](client-secret-agent) | Anywhere, with no workload identity | Exchanges an id and secret for a Hush token | |

## Before you start

Every example needs:

- **A Hush API key** for Terraform, which creates the agent and, for it to
  try, a DeepWiki app on your gateway. Create it in the Hush console under
  API Keys, with the `admin:read`, `admin:write`, `applications:read` and
  `applications:write` privileges, then:

  ```sh
  export HUSH_API_KEY_ID=<key id> HUSH_API_KEY_SECRET=<key secret>
  ```

- **Your gateway's details**: its MCP URL (`https://<gateway>/mcp`), and from
  it, its issuer and deployment id:

  ```sh
  curl -s https://<gateway>/.well-known/oauth-protected-resource/mcp | jq -r '.authorization_servers[0]'
  # https://api.us.hush-security.com/v1/deployments/<deployment id>/agents
  ```

## The basics

- A **service agent** in Hush
  ([`hush_service_agent`](https://registry.terraform.io/providers/hushsecurity/hush/latest/docs/resources/service_agent))
  names the workload identities it signs in with: a Kubernetes service
  account, an AWS IAM role, an Azure / Entra service principal, or any OIDC
  issuer; or, with no workload identity, a client secret.
- The workload's token must be issued **for the gateway**. Its audience is
  the gateway's issuer, which the gateway publishes at
  `https://<gateway>/.well-known/oauth-protected-resource/mcp`
  (`authorization_servers`). Azure / Entra tokens are the exception: there,
  the audience is an app registration you create for the gateway (see
  [`entra-agent`](entra-agent), [`foundry-agent`](foundry-agent) and
  [`azure-managed-identity`](azure-managed-identity)).
- **Two ways to connect.** The agent sends its workload's token to the
  gateway as the Bearer, and the gateway exchanges it with Hush (on-prem
  gateways need the `hush-agw` chart 0.7.1 or later). Or the agent exchanges
  it at Hush's token endpoint itself and sends the Hush token: a standard
  OAuth token, which any MCP client can use.
- **Acting for a user.** An Entra on-behalf-of token names both the user and
  the agent, so it works as the Bearer. Other workload tokens never name a
  user: the agent exchanges its token together with the user's Hush token
  (RFC 8693 token exchange). Either way, the service agent needs
  `acts_for_users`.
- Apps are granted to a service agent with an assignment rule on its id.
  Assigning an app to all users does not cover service agents.

## License

[Apache 2.0](LICENSE)
