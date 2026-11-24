# AgentCore outbound auth: Hush as a credential provider

An LLM agent on [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/)
gets its token for the Hush AI gateway from **AgentCore Identity**: Hush is a
credential provider in AgentCore's token vault, and the agent asks for a
token with the standard `@requires_access_token` decorator. The agent has no
token code and no secret: AgentCore signs in to Hush with the runtime role's
AWS token.

- **For a user** (`ON_BEHALF_OF_TOKEN_EXCHANGE`, the default): AgentCore
  checks the user's token at the runtime's door, then exchanges it at Hush
  (RFC 8693) for a token naming the user and the agent. The gateway applies
  the user's access through the agent.
- **As itself** (`M2M`): the token names only the agent.

```
user ──(token)──▶ AgentCore door ──▶ agent: @requires_access_token
                                          │ AgentCore Identity ──(AWS token + user's token)──▶ Hush
                                          ▼
                                 agent ──(Bearer: Hush token)──▶ gateway
```

[`agentcore-agent`](../agentcore-agent) does the same in the agent's own
code. Use this one when you already use AgentCore's outbound auth, or want
AgentCore to hold the exchange.

## Requirements

- A Hush AI gateway that AgentCore can reach: hosted, or on-prem with a public
  address.
- An AWS account with outbound identity federation enabled, once:
  `aws iam enable-outbound-web-identity-federation`.
- The AgentCore starter toolkit (`pip install bedrock-agentcore-starter-toolkit`),
  the AWS CLI, Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.
- For a user: an identity provider that is your gateway's identity provider,
  whose tokens for an app name users Hush knows (Entra ID, Okta, Ping), or
  Hush itself (see [Hush at the door](#or-hush-at-the-door)).

## Files

| File | What it is |
| ---- | ---------- |
| [`agent.py`](agent.py) | The agent: a Strands agent whose MCP server is the gateway, with its token from `@requires_access_token` |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the runtime's IAM role, a DeepWiki app granted to it, and the credential provider's settings |

## Run it

1. **Deploy the agent to AgentCore**, with your identity provider at its
   door. The toolkit creates the runtime's execution role.

   ```sh
   agentcore configure --entrypoint agent.py --name hush_outbound_auth \
     --region us-east-1 --requirements-file requirements.txt --disable-memory --non-interactive \
     --authorizer-config '{"customJWTAuthorizer": {"discoveryUrl": "<your issuer>/.well-known/openid-configuration", "allowedAudience": ["<app audience>"]}}'
   agentcore deploy -a hush_outbound_auth \
     --env HUSH_GATEWAY_URL=https://<gateway>/mcp --env MODEL_ID=us.anthropic.claude-sonnet-5
   ```

2. **Register the agent in Hush**, bound to that role, and accepting your
   provider's user tokens for the app.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> \
     -var idp_audience=<app audience> \
     -var aws_issuer="$(aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text)" \
     -var role_arn="$(python3 -c "import yaml; print(yaml.safe_load(open('.bedrock_agentcore.yaml'))['agents']['hush_outbound_auth']['aws']['execution_role'])")"
   ```

3. **Add Hush as a credential provider** in AgentCore Identity (`hush`, the
   name the agent asks for):

   ```sh
   aws bedrock-agentcore-control create-oauth2-credential-provider --region us-east-1 \
     --name hush --credential-provider-vendor CustomOauth2 \
     --oauth2-provider-config-input "$(terraform -chdir=terraform output -raw credential_provider)"
   ```

   In the console (Identity → Outbound Auth → Add OAuth client → Custom
   provider), the same is: manual configuration with the gateway's issuer,
   its `/oauth/authorize`, and its **`/oauth/token`**
   (`https://<api>/v1/deployments/<deployment id>/agents/oauth/token`); the
   service agent's id as the client id; client authentication "AWS IAM ID
   token"; and on-behalf-of token exchange.

4. **Ask it something, as a user:**

   ```sh
   agentcore invoke '{"prompt": "Using DeepWiki, list the wiki pages of modelcontextprotocol/python-sdk."}' \
     -a hush_outbound_auth --bearer-token "<a user's token for your app>"
   ```

## Or as itself

Deploy with `--env AUTH_FLOW=M2M`: AgentCore gets the agent a token of its
own, and the user at the door is not passed on. As itself, the agent can use
only apps that need no user's sign-in.

## Or Hush at the door

Without an identity provider of your own, Hush can check users at the door:
users sign in to Hush for the agent (see
[`agentcore-agent`'s `sign_in.py`](../agentcore-agent/sign_in.py)), and the
agent is unchanged. This needs a Hush release from late November 2026 or
later.

```sh
ISSUER=$(curl -s https://<gateway>/.well-known/oauth-protected-resource/mcp \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['authorization_servers'][0])")
RESOURCE=$(terraform -chdir=terraform output -raw resource)
agentcore configure ... \
  --authorizer-config "{\"customJWTAuthorizer\": {\"discoveryUrl\": \"$ISSUER/.well-known/openid-configuration\", \"allowedAudience\": [\"$RESOURCE\"]}}"
agentcore deploy -a hush_outbound_auth ...
```

A user's Hush token lasts 5 minutes, so invoke right after signing in.

## The options

`@requires_access_token` and the provider's settings, with Hush as the
provider:

| `auth_flow` | Client authentication | What the agent gets |
| ----------- | --------------------- | ------------------- |
| `ON_BEHALF_OF_TOKEN_EXCHANGE` | AWS IAM ID token (this example) | A token for the user at the door and the agent, with no secret |
| `ON_BEHALF_OF_TOKEN_EXCHANGE` | Client secret | The same, with a client secret on the service agent (`hush_service_agent_client_secret`) as the client secret |
| `M2M` | AWS IAM ID token, or client secret | A token for the agent itself |
| `USER_FEDERATION` | — | Not shown here: the user signs in (3LO) during the agent's run |

## Good to know

- **The token endpoint is the gateway's own**, under its issuer: AgentCore
  addresses the AWS token to the token endpoint, and that names the gateway
  to Hush. Use it in place of the one in the issuer's metadata.
- **`resources` is the gateway's MCP URL**: the token is for it. For
  [your own API](../your-api), use the API's audience and scopes.
- **The agent asks for a token per invocation**; for long runs, ask again
  before it expires.
- **The agent never reads the user's token**: AgentCore keeps it from the
  door and exchanges it, so no `--request-header-allowlist` is needed.
- **Limit which users the agent acts for** with `assignment` rules on the
  service agent; without any, it may act for every user.
- **Acting for a user, the agent can use an app that names it and admits
  that user.** The example's DeepWiki admits every user (`assign_all`).

## Clean up

```sh
aws bedrock-agentcore-control delete-oauth2-credential-provider --region us-east-1 --name hush
agentcore destroy -a hush_outbound_auth
terraform -chdir=terraform destroy
```
