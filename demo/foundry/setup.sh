#!/usr/bin/env bash
# Connects your Foundry project to the gateway, twice: one connection for the
# agent acting as itself, one for it acting for the signed-in user. Run it
# signed in to the project's tenant with `az login`. Needs curl and jq.
#
#   ./setup.sh <Foundry project resource id> https://<gateway>/mcp
set -euo pipefail
PROJECT_ID=$1
GATEWAY_URL=$2
CONNECTIONS="https://management.azure.com$PROJECT_ID/connections"

# 1. The gateway's API, for the agent's own tokens. Use it for Hush only.
GATEWAY_API=$(az ad app create --display-name "Hush gateway (demo)" --query appId -o tsv)
az rest -m PATCH -u "https://graph.microsoft.com/v1.0/applications(appId='$GATEWAY_API')" \
  --headers Content-Type=application/json \
  -b '{"identifierUris": ["api://'"$GATEWAY_API"'"], "api": {"requestedAccessTokenVersion": 2}}'
az ad sp create --id "$GATEWAY_API" -o none

# 2. As itself: the agent calls the gateway with its agent identity's token.
az rest -m PUT -u "$CONNECTIONS/hush-demo-agent?api-version=2025-04-01-preview" \
  --headers Content-Type=application/json -o none -b '{
  "properties": {
    "category": "RemoteTool", "authType": "AgenticIdentityToken",
    "target": "'"$GATEWAY_URL"'", "audience": "api://'"$GATEWAY_API"'",
    "metadata": {"type": "generic_mcp"}
  }
}'

# 3. For the user: Foundry signs each user in to the gateway once (OAuth
#    identity passthrough) and calls it with their own Hush token.
ISSUER=$(curl -fsS "${GATEWAY_URL%/mcp}/.well-known/oauth-protected-resource/mcp" | jq -r '.authorization_servers[0]')
OAUTH=$(curl -fsS "$ISSUER/.well-known/oauth-authorization-server")
user_connection() {
  az rest -m PUT -u "$CONNECTIONS/hush-demo-user?api-version=2025-04-01-preview" \
    --headers Content-Type=application/json --query properties.redirectUrl -o tsv -b '{
    "properties": {
      "category": "RemoteTool", "authType": "OAuth2", "target": "'"$GATEWAY_URL"'",
      "authorizationUrl": "'"$(jq -r .authorization_endpoint <<< "$OAUTH")"'",
      "tokenUrl": "'"$(jq -r .token_endpoint <<< "$OAUTH")"'",
      "refreshUrl": "'"$(jq -r .token_endpoint <<< "$OAUTH")"'",
      "scopes": ["offline_access"], "credentials": {"clientId": "'"$1"'"},
      "metadata": {"type": "generic_mcp"}
    }
  }'
}
# Foundry assigns the connection's redirect URL when it's created, and reads
# the client id only then: create it, register a Hush client for that URL,
# then create it again with the client's id.
REDIRECT=$(user_connection 00000000-0000-0000-0000-000000000000)
CLIENT=$(curl -fsS -X POST "$(jq -r .registration_endpoint <<< "$OAUTH")" -H 'Content-Type: application/json' \
  -d '{"client_name": "Foundry (demo)", "redirect_uris": ["'"$REDIRECT"'"], "token_endpoint_auth_method": "none"}' \
  | jq -r .client_id)
user_connection "$CLIENT" > /dev/null

cat <<EOF

export TF_VAR_tenant_id=$(az account show --query tenantId -o tsv)
export TF_VAR_foundry_gateway_api_id=$GATEWAY_API
EOF
