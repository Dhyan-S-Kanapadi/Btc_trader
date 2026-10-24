variable "aws_region" {
  description = "AWS Region for this paper-trading stack."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Lowercase resource-name prefix."
  type        = string
  default     = "btc-paper-trader"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "project_name must contain only lowercase letters, digits, and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "paper"
}

variable "vpc_cidr" {
  description = "Private RFC1918 range reserved for this stack."
  type        = string
  default     = "10.31.0.0/16"
}

variable "db_instance_class" {
  description = "Small PostgreSQL instance class; an assumption to review before sustained use."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL engine version verified as orderable in us-east-1 on 2026-10-24."
  type        = string
  default     = "16.15"
}

variable "db_backup_retention_days" {
  description = "Days of automated RDS backups retained."
  type        = number
  default     = 7

  validation {
    condition     = var.db_backup_retention_days >= 1 && var.db_backup_retention_days <= 35
    error_message = "db_backup_retention_days must be between 1 and 35."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD; an operational assumption, not a spend cap."
  type        = number
  default     = 50

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than zero."
  }
}

variable "budget_alert_email" {
  description = "Required email recipient for AWS Budget notifications. Keep it out of version control."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be a valid email address."
  }
}

variable "app_image_tag" {
  description = "Immutable ECR image tag produced by CI; required before ECS tasks can be deployed."
  type        = string

  validation {
    condition     = length(trimspace(var.app_image_tag)) > 0
    error_message = "app_image_tag must name an immutable image produced by CI."
  }
}

variable "agent_image_tag" {
  description = "Immutable AgentCore runtime image tag produced from Dockerfile.agent; required before deployment."
  type        = string

  validation {
    condition     = length(trimspace(var.agent_image_tag)) > 0
    error_message = "agent_image_tag must name an immutable AgentCore image produced by CI."
  }
}

variable "groq_model" {
  description = "Groq model identifier for the investigator; this is an operational assumption, not a trading parameter."
  type        = string
  default     = "openai/gpt-oss-20b"
}

variable "api_ingress_cidrs" {
  description = "CIDRs allowed to reach the read-only API load balancer; public access is an assumption until the dashboard is deployed."
  type        = list(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = alltrue([for cidr in var.api_ingress_cidrs : can(cidrhost(cidr, 0))])
    error_message = "api_ingress_cidrs must contain valid CIDR blocks."
  }
}

variable "log_retention_days" {
  description = "CloudWatch application-log retention; 30 days is an operational assumption."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_days)
    error_message = "log_retention_days must be a supported CloudWatch retention value."
  }
}
