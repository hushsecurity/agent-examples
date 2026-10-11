terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.28"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID and HUSH_API_KEY_SECRET.
provider "hush" {}

variable "tenant_id" {
  description = "ENTRA_TENANT_ID from setup.sh"
  type        = string
}

variable "principal_id" {
  description = "AZURE_PRINCIPAL_ID from setup.sh: the managed identity's object id"
  type        = string
}

variable "gateway_api_id" {
  description = "ENTRA_GATEWAY_API_ID from setup.sh"
  type        = string
}

# The agent, signing in as its managed identity.
resource "hush_service_agent" "example" {
  name = "azure-managed-identity"

  azure {
    tenant_id            = var.tenant_id
    service_principal_id = var.principal_id
    audience             = var.gateway_api_id
  }
}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

# DeepWiki's public MCP server. It needs no sign-in, so the agent can use it
# as itself. Its tools are listed as read, which the gateway allows.
resource "hush_custom_mcp_application" "deepwiki" {
  name         = "deepwiki-azure-managed-identity"
  display_name = "DeepWiki (azure-managed-identity example)"

  url {
    url = "https://mcp.deepwiki.com/mcp"
  }

  tool {
    name = "read_wiki_structure"
    type = "read"
  }
  tool {
    name = "read_wiki_contents"
    type = "read"
  }
  tool {
    name = "ask_wiki_question"
    type = "read"
  }
}

# DeepWiki on the gateway, granted to the agent.
resource "hush_mcp_application" "deepwiki" {
  app_catalog_id = hush_custom_mcp_application.deepwiki.app_catalog_id
  display_name   = hush_custom_mcp_application.deepwiki.display_name
  deployment_ids = [var.deployment_id]

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
}

output "agent_id" {
  description = "Grant more apps to the agent with an assignment rule on agent.id = this."
  value       = hush_service_agent.example.id
}
