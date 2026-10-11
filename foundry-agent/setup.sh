#!/usr/bin/env bash
# Creates the Azure side of the example: the gateway's API in Entra, and a
# connection from your Foundry project to the gateway. Run it signed in to the
# tenant with `az login`.
#
#   ./setup.sh <Foundry project resource id> https://<gateway>/mcp
#
# The project's resource id is on its overview page in the Azure portal:
# /subscriptions/<id>/resourceGroups/<group>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>
set -euo pipefail
PROJECT_ID=$1
GATEWAY_URL=$2

# 1. The gateway's API: what the agent requests its tokens for. Use it for
#    Hush only, since anything that receives its tokens could replay them.
GATEWAY_API=$(az ad app create --display-name "Hush gateway (Foundry)" --query appId -o tsv)
az rest -m PATCH -u "https://graph.microsoft.com/v1.0/applications(appId='$GATEWAY_API')" \
  --headers Content-Type=application/json \
  -b '{"identifierUris": ["api://'"$GATEWAY_API"'"], "api": {"requestedAccessTokenVersion": 2}}'
az ad sp create --id "$GATEWAY_API" -o none

# 2. The project's connection to the gateway. With AgenticIdentityToken, each
#    agent calls the gateway with a token for its own agent identity.
az rest -m PUT -u "https://management.azure.com$PROJECT_ID/connections/hush-gateway?api-version=2025-04-01-preview" \
  --headers Content-Type=application/json -o none -b '{
  "properties": {
    "category": "RemoteTool",
    "authType": "AgenticIdentityToken",
    "target": "'"$GATEWAY_URL"'",
    "audience": "api://'"$GATEWAY_API"'",
    "metadata": {"type": "generic_mcp"}
  }
}'

cat <<EOF

export ENTRA_TENANT_ID=$(az account show --query tenantId -o tsv)
export ENTRA_GATEWAY_API_ID=$GATEWAY_API
EOF
