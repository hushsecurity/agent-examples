#!/usr/bin/env bash
# Creates the Entra side of the example in the tenant you're signed in to with
# `az login`. Needs the Agent ID Administrator and Cloud Application
# Administrator roles. Prints the values agent.py and the Terraform need.
set -euo pipefail

GRAPH=https://graph.microsoft.com/beta
ME=$(az ad signed-in-user show --query id -o tsv)
TENANT=$(az account show --query tenantId -o tsv)
AZURE_CLI=04b07795-8ddb-461a-bbee-02f9e1bf7b46
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
# New Entra objects take a few seconds to reach every replica: retry the
# steps that use one right after it's created.
retry() { for _ in 1 2 3 4 5 6; do "$@" && return; sleep 10; done; return 1; }
graph() { az rest -m "$1" -u "$GRAPH/$2" --headers Content-Type=application/json -b "${3:-}" "${@:4}"; }

# 1. The gateway's API: what the agent requests its tokens for. Use it for
#    Hush only, since anything that receives its tokens could replay them.
GATEWAY_API=$(az ad app create --display-name "Hush gateway" --query appId -o tsv)
graph PATCH "applications(appId='$GATEWAY_API')" '{
  "identifierUris": ["api://'"$GATEWAY_API"'"],
  "api": {
    "requestedAccessTokenVersion": 2,
    "oauth2PermissionScopes": [{
      "id": "'"$(uuid)"'", "value": "gateway.access", "type": "User", "isEnabled": true,
      "adminConsentDisplayName": "Use the Hush gateway",
      "adminConsentDescription": "Lets an agent call the Hush gateway for the signed-in user."
    }]
  }
}'
GATEWAY_API_SP=$(retry az ad sp create --id "$GATEWAY_API" --query id -o tsv)

# 2. The agent: a blueprint, and an agent identity created from it.
ME_REF='["https://graph.microsoft.com/v1.0/users/'"$ME"'"]'
BLUEPRINT=$(graph POST applications '{
  "@odata.type": "Microsoft.Graph.AgentIdentityBlueprint",
  "displayName": "Hush example agent blueprint",
  "sponsors@odata.bind": '"$ME_REF"',
  "owners@odata.bind": '"$ME_REF"'
}' --query appId -o tsv)
retry graph POST serviceprincipals/graph.agentIdentityBlueprintPrincipal '{"appId": "'"$BLUEPRINT"'"}' -o none
AGENT=$(retry graph POST serviceprincipals/Microsoft.Graph.AgentIdentity '{
  "displayName": "Hush example agent",
  "agentIdentityBlueprintId": "'"$BLUEPRINT"'",
  "sponsors@odata.bind": '"$ME_REF"'
}' --query appId -o tsv)

# 3. For --as-user: users sign in to the agent (its blueprint) with the
#    access_as_user scope. The Azure CLI is pre-authorized so the example can
#    get a user token with `az`; an app's own front end takes its place.
USER_SCOPE=$(uuid)
graph PATCH "applications(appId='$BLUEPRINT')" '{
  "identifierUris": ["api://'"$BLUEPRINT"'"],
  "api": {
    "oauth2PermissionScopes": [{
      "id": "'"$USER_SCOPE"'", "value": "access_as_user", "type": "User", "isEnabled": true,
      "adminConsentDisplayName": "Use the agent",
      "adminConsentDescription": "Lets the agent act for the signed-in user.",
      "userConsentDisplayName": "Use the agent",
      "userConsentDescription": "Lets the agent act for you."
    }]
  }
}'
# A separate request: the scope must exist before anything can name it.
retry graph PATCH "applications(appId='$BLUEPRINT')" '{
  "api": {
    "preAuthorizedApplications": [{"appId": "'"$AZURE_CLI"'", "permissionIds": ["'"$USER_SCOPE"'"]}]
  }
}'

# 4. Admin consent: the agent may call the gateway for any user of the tenant.
#    Agent identities can't ask users for consent themselves. (An agent
#    identity's app id is also its service principal's id.)
retry az rest -m POST -u https://graph.microsoft.com/v1.0/oauth2PermissionGrants \
  --headers Content-Type=application/json -o none -b '{
  "clientId": "'"$AGENT"'", "consentType": "AllPrincipals",
  "resourceId": "'"$GATEWAY_API_SP"'", "scope": "gateway.access"
}'

# 5. A secret for the blueprint, to run the example from anywhere. In
#    production, prefer a federated credential (e.g. a managed identity).
SECRET=$(graph POST "applications(appId='$BLUEPRINT')/addPassword" \
  '{"passwordCredential": {"displayName": "hush-example"}}' --query secretText -o tsv)

cat <<EOF

export ENTRA_TENANT_ID=$TENANT
export ENTRA_BLUEPRINT_ID=$BLUEPRINT
export ENTRA_BLUEPRINT_SECRET='$SECRET'
export ENTRA_AGENT_ID=$AGENT
export ENTRA_GATEWAY_API_ID=$GATEWAY_API
EOF
