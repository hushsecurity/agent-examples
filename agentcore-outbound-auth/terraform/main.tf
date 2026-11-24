terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.40"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID and HUSH_API_KEY_SECRET.
provider "hush" {}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

variable "aws_issuer" {
  description = "The AWS account's issuer: aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text"
  type        = string
}

variable "role_arn" {
  description = "The AgentCore runtime's execution role"
  type        = string
}

variable "idp_audience" {
  description = "With your identity provider at AgentCore's door: the app its user tokens are for"
  type        = string
  default     = null
}

# The agent, signing in as its runtime's IAM role: AgentCore Identity sends
# that role's AWS token to Hush for it.
resource "hush_service_agent" "example" {
  name           = "agentcore-outbound-auth"
  acts_for_users = true

  aws_iam_role {
    issuer   = var.aws_issuer
    role_arn = var.role_arn
  }

  # Accept the user's identity provider token for this app, not only a Hush one.
  dynamic "user_tokens" {
    for_each = var.idp_audience == null ? [] : [1]
    content {
      audiences = [var.idp_audience]
    }
  }
}

# DeepWiki's public MCP server. It needs no sign-in, so the agent can use it
# as itself. Its tools are listed as read, which the gateway allows.
resource "hush_custom_mcp_application" "deepwiki" {
  name         = "deepwiki-agentcore-outbound-auth"
  display_name = "DeepWiki (agentcore-outbound-auth example)"

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

# DeepWiki on the gateway, granted to the agent. Acting for a user, the agent
# also needs the app to admit that user: here, every user (assign_all).
resource "hush_mcp_application" "deepwiki" {
  app_catalog_id = hush_custom_mcp_application.deepwiki.app_catalog_id
  display_name   = hush_custom_mcp_application.deepwiki.display_name
  deployment_ids = [var.deployment_id]
  assign_all     = true

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

data "hush_agent_authorization_server" "gateway" {
  deployment_id = var.deployment_id
}

locals {
  issuer = data.hush_agent_authorization_server.gateway.issuer
}

output "resource" {
  description = "What users sign in to Hush for, with Hush at AgentCore's door."
  value       = hush_service_agent.example.resource
}

# Hush as an AgentCore credential provider. The token endpoint is the one
# under the gateway's issuer: AgentCore addresses the AWS token to it.
output "credential_provider" {
  description = "The AgentCore credential provider's settings (--oauth2-provider-config-input)."
  value = jsonencode({
    customOauth2ProviderConfig = {
      oauthDiscovery = {
        authorizationServerMetadata = {
          issuer                = local.issuer
          authorizationEndpoint = "${local.issuer}/oauth/authorize"
          tokenEndpoint         = "${local.issuer}/oauth/token"
        }
      }
      clientId                   = hush_service_agent.example.id
      clientAuthenticationMethod = "AWS_IAM_ID_TOKEN_JWT"
      onBehalfOfTokenExchangeConfig = {
        grantType                    = "TOKEN_EXCHANGE"
        tokenExchangeGrantTypeConfig = { actorTokenContent = "NONE" }
      }
    }
  })
}
