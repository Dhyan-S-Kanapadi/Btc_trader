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
