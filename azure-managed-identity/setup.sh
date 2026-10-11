#!/usr/bin/env bash
# Creates the Azure side of the example: the gateway's API in Entra, and a
# managed identity for the agent. Run it signed in with `az login`.
#
#   ./setup.sh <resource group> <region>
set -euo pipefail
GROUP=$1
REGION=$2

# 1. The gateway's API: what the agent requests its tokens for. Use it for
#    Hush only, since anything that receives its tokens could replay them.
GATEWAY_API=$(az ad app create --display-name "Hush gateway (managed identity)" --query appId -o tsv)
az rest -m PATCH -u "https://graph.microsoft.com/v1.0/applications(appId='$GATEWAY_API')" \
  --headers Content-Type=application/json \
  -b '{"identifierUris": ["api://'"$GATEWAY_API"'"], "api": {"requestedAccessTokenVersion": 2}}'
az ad sp create --id "$GATEWAY_API" -o none

# 2. The agent's managed identity.
az group create -n "$GROUP" -l "$REGION" -o none
az identity create -g "$GROUP" -n hush-example-agent -o none
identity() { az identity show -g "$GROUP" -n hush-example-agent --query "$1" -o tsv; }

cat <<EOF

export ENTRA_TENANT_ID=$(az account show --query tenantId -o tsv)
export ENTRA_GATEWAY_API_ID=$GATEWAY_API
export AZURE_IDENTITY=$(identity id)
export AZURE_CLIENT_ID=$(identity clientId)
export AZURE_PRINCIPAL_ID=$(identity principalId)
EOF
