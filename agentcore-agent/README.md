# AgentCore agent: AWS identity, as itself and for a user

An agent on [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/)
uses the Hush AI gateway as its MCP server. It proves who it is with its
runtime's IAM role: `sts:GetWebIdentityToken` gives it an AWS-signed token
issued for the gateway.

The agent calls the gateway in two ways:

- **As itself** (`{"prompt": ...}`): it sends the AWS token as the Bearer, and
  the gateway exchanges it with Hush. It uses the apps granted to the agent.
- **For a user** (`{"prompt": ..., "user_token": ...}`): an AWS token never
  names a user, so the agent exchanges it at Hush, together with the user's
  Hush token, for a token naming both (RFC 8693 token exchange). The gateway
  applies the user's access through the agent.

```
as itself:  agent ──(Bearer: AWS token)──▶ gateway ──(exchange)──▶ Hush
for a user: agent ──(AWS token + user's Hush token)──▶ Hush ──▶ token for both
            agent ──(Bearer: that token)──▶ gateway
```

## Requirements

- A Hush AI gateway that AgentCore can reach: hosted, or on-prem with a public
  address (`hush-agw` chart 0.7.1 or later).
- An AWS account with outbound identity federation enabled, once per account:
  `aws iam enable-outbound-web-identity-federation`.
- The AgentCore starter toolkit (`pip install bedrock-agentcore-starter-toolkit`),
  Terraform with a Hush API key (`HUSH_API_KEY_ID`, `HUSH_API_KEY_SECRET`,
  `HUSH_REALM`), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`agent.py`](agent.py) | The agent: a Strands agent whose MCP server is the gateway, and the two ways to sign in |
| [`requirements.txt`](requirements.txt) | Its dependencies |
| [`terraform/main.tf`](terraform/main.tf) | The service agent in Hush, bound to the runtime's IAM role |
| [`sign_in.py`](sign_in.py) | Signs a user in for the agent, to try `user_token` (standard library only) |

## Run it

1. **Deploy the agent to AgentCore.**

   ```sh
   agentcore configure --entrypoint agent.py --name hush_example_agent \
     --region us-east-1 --requirements-file requirements.txt --disable-memory --non-interactive
   agentcore deploy -a hush_example_agent \
     --env HUSH_GATEWAY_URL=https://<gateway>/mcp \
     --env MODEL_ID=us.anthropic.claude-sonnet-5
   ```

   The toolkit creates the runtime's execution role, with
   `sts:GetWebIdentityToken` allowed. If you bring your own role, allow it.

2. **Register the agent in Hush**, bound to that role.

   ```sh
   cd terraform
   terraform init
   terraform apply \
     -var aws_issuer="$(aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text)" \
     -var role_arn="$(python3 -c "import yaml; print(yaml.safe_load(open('../.bedrock_agentcore.yaml'))['agents']['hush_example_agent']['aws']['execution_role'])")"
   ```

3. **Grant it apps.** Assigning an app to all users does not cover service
   agents: add a rule on the agent's id to each app it should use as itself.
   Acting for a user, it gets the user's apps.

   ```hcl
   assignment {
     condition {
       match {
         source   = "agent"
         property = "id"
         op       = "eq"
         value    = hush_service_agent.example.id
       }
     }
   }
   ```

   As itself, the agent can use only apps that need no user's sign-in: an
   app with no authentication, or one connected with a service account or API
   key. Apps connected with each user's OAuth consent need an agent acting
   for a user.

4. **Ask it something, as itself.**

   ```sh
   agentcore invoke '{"prompt": "Which apps can you use?"}' -a hush_example_agent
   ```

5. **Ask it something, for a user.** Sign in (it opens your browser), then
   pass your token to the agent:

   ```sh
   python sign_in.py https://<gateway>/mcp "$(terraform -chdir=terraform output -raw resource)"
   agentcore invoke "{\"prompt\": \"Which apps can I use?\", \"user_token\": \"$(cat .user-token)\"}" -a hush_example_agent
   ```

   In an app, your front end signs the user in and passes their token to the
   agent with each request.

## How the agent gets its token

- `discover()`: the gateway's `/.well-known/oauth-protected-resource/mcp`
  names its issuer (the AWS token's audience), and the issuer's
  `/.well-known/oauth-authorization-server` names Hush's token endpoint.
- `aws_token()`: `sts:GetWebIdentityToken` with the issuer as the audience.
- `hush_token_for(user_token)`: posts to the token endpoint

  ```
  grant_type=urn:ietf:params:oauth:grant-type:token-exchange
  subject_token=<user's Hush token>
  subject_token_type=urn:ietf:params:oauth:token-type:access_token
  client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
  client_assertion=<AWS token>
  ```

- `Bearer`: sends the current token, getting a new one a minute before it
  expires.

## In your own agent

- **The user's token must be for this agent.** The user signs in with
  `resource` set to the agent's `resource` (Terraform output); a token for
  anything else is refused.
- **The agent needs `acts_for_users`** to act for users.
- **Any MCP client works.** Only the `Authorization` header is specific to
  Hush.

## Troubleshooting

- **`401` from the gateway, as itself**: the role isn't registered
  (`role_arn` and `aws_issuer` must match), or the AWS token's audience isn't
  the gateway's issuer.
- **`Hush refused (400): ...` for a user**: the message names the problem:
  the user's token is for another agent or deployment, it expired (sign in
  again), or the agent has no `acts_for_users`.
- **`AccessDenied` from STS**: outbound identity federation isn't enabled in
  the account, or the role isn't allowed `sts:GetWebIdentityToken`.
- See the runtime's logs with `aws logs tail /aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT --follow`.

## Clean up

```sh
agentcore destroy -a hush_example_agent
terraform -chdir=terraform destroy
```
