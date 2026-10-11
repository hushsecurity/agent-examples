# AgentCore agent: AWS identity, as itself and for a user

An LLM agent on [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/)
uses the Hush AI gateway as its MCP server. It proves who it is with its
runtime's IAM role: `sts:GetWebIdentityToken` gives it an AWS token issued
for the gateway.

- **As itself** (`{"prompt": ...}`): it sends the AWS token as the Bearer,
  and the gateway exchanges it with Hush.
- **For a user** (`{"prompt": ..., "user_token": ...}`): an AWS token never
  names a user, so the agent exchanges it together with the user's Hush token
  at Hush (RFC 8693 token exchange) for a token naming both. The gateway
  applies the user's access through the agent.

```
as itself:  agent ──(Bearer: AWS token)──▶ gateway ──(exchange)──▶ Hush
for a user: agent ──(AWS token + user's Hush token)──▶ Hush ──▶ token for both
            agent ──(Bearer: that token)──▶ gateway
```

The same works on any AWS compute with an IAM role (ECS, Lambda, EC2): only
the deployment differs.

## Requirements

- A Hush AI gateway that AgentCore can reach: hosted, or on-prem with a public
  address (`hush-agw` chart 0.7.1 or later).
- An AWS account with outbound identity federation enabled, once:
  `aws iam enable-outbound-web-identity-federation`.
- The AgentCore starter toolkit (`pip install bedrock-agentcore-starter-toolkit`),
  Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`agent.py`](agent.py) | The agent: a Strands agent whose MCP server is the gateway, and its two ways to sign in |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the runtime's IAM role, and a DeepWiki app granted to it |
| [`sign_in.py`](sign_in.py) | Signs a user in for the agent (standard library only) |

## Run it

1. **Deploy the agent to AgentCore.** The toolkit creates the runtime's
   execution role, with `sts:GetWebIdentityToken` allowed (allow it yourself
   on a role you bring).

   ```sh
   agentcore configure --entrypoint agent.py --name hush_example_agent \
     --region us-east-1 --requirements-file requirements.txt --disable-memory --non-interactive
   agentcore deploy -a hush_example_agent \
     --env HUSH_GATEWAY_URL=https://<gateway>/mcp --env MODEL_ID=us.anthropic.claude-sonnet-5
   ```

2. **Register the agent in Hush**, bound to that role. Terraform creates the
   service agent, and DeepWiki (a public MCP server that needs no sign-in) on
   your gateway, granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> \
     -var aws_issuer="$(aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text)" \
     -var role_arn="$(python3 -c "import yaml; print(yaml.safe_load(open('.bedrock_agentcore.yaml'))['agents']['hush_example_agent']['aws']['execution_role'])")"
   ```

3. **Ask it something, as itself.**

   ```sh
   agentcore invoke '{"prompt": "Using DeepWiki, list the wiki pages of modelcontextprotocol/python-sdk."}' -a hush_example_agent
   ```

4. **Ask it something, for a user.** Sign in (it opens your browser), then
   pass your token to the agent:

   ```sh
   python sign_in.py https://<gateway>/mcp "$(terraform -chdir=terraform output -raw resource)"
   agentcore invoke "{\"prompt\": \"Using DeepWiki, list the wiki pages of modelcontextprotocol/python-sdk.\", \"user_token\": \"$(cat .user-token)\"}" -a hush_example_agent
   ```

   A user's token lasts 5 minutes, so invoke right after signing in. In an
   app, your front end keeps the user signed in and passes a fresh token with
   each request.

## Good to know

- **As itself, the agent could also exchange its AWS token at Hush** (client
  credentials, with the AWS token as the client assertion) and send the Hush
  token, like [`k8s-agent-exchange`](../k8s-agent-exchange); for a user, it
  must.
- **The gateway's issuer and Hush's token endpoint are discovered from the
  gateway's URL** (`discover()`), the standard MCP way. The issuer is the AWS
  token's audience.
- **The user's token must be for this agent**: users sign in with `resource`
  set to the agent's `resource` (Terraform output). The agent needs
  `acts_for_users`.
- **As itself, the agent can use only apps that need no user's sign-in.**
  Grant it more apps with an assignment rule on `agent.id`.
- **A `401` from the gateway** usually means the role isn't registered
  (`role_arn` and `aws_issuer` must match). **`AccessDenied` from STS** means
  federation isn't enabled, or the role isn't allowed
  `sts:GetWebIdentityToken`. The runtime's logs:
  `aws logs tail /aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT --follow`.

## Clean up

```sh
agentcore destroy -a hush_example_agent
terraform -chdir=terraform destroy
```
