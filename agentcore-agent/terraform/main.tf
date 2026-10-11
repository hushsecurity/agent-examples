terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.28"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID, HUSH_API_KEY_SECRET and HUSH_REALM.
provider "hush" {}

variable "aws_issuer" {
  description = "The AWS account's issuer: aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text"
  type        = string
}

variable "role_arn" {
  description = "The AgentCore runtime's execution role"
  type        = string
}

# The agent, signing in as its runtime's IAM role. acts_for_users lets it act
# for users as well.
resource "hush_service_agent" "example" {
  name           = "agentcore-example-agent"
  acts_for_users = true

  aws_iam_role {
    issuer   = var.aws_issuer
    role_arn = var.role_arn
  }
}

output "agent_id" {
  description = "Grant apps to the agent with an assignment rule on agent.id = this."
  value       = hush_service_agent.example.id
}

output "resource" {
  description = "What users sign in for, to let the agent act for them (sign_in.py)."
  value       = hush_service_agent.example.resource
}
