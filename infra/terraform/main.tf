data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    TradingMode = "paper-only"
  }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count = length(local.azs)

  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  map_public_ip_on_launch = false

  tags = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count = length(local.azs)

  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + length(local.azs))

  tags = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = { Name = "${local.name}-nat" }
}

# shortcut: one NAT gateway reduces early paper-trading cost; use one per AZ before high-availability production.
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  depends_on = [aws_internet_gateway.main]

  tags = { Name = "${local.name}-nat" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count = length(aws_subnet.private)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "PostgreSQL only from paper-trader application security groups."
  vpc_id      = aws_vpc.main.id
  egress      = []

  tags = { Name = "${local.name}-rds" }
}

resource "aws_security_group" "app" {
  for_each = toset(["worker", "api", "agent"])

  name        = "${local.name}-${each.key}"
  description = "No inbound access; outbound DNS, HTTPS, and PostgreSQL only."
  vpc_id      = aws_vpc.main.id

  egress {
    description = "HTTPS to public market data, Groq, and AWS APIs."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "DNS within the VPC."
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = { Name = "${local.name}-${each.key}" }
}

resource "aws_vpc_security_group_ingress_rule" "rds_postgres" {
  for_each = aws_security_group.app

  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = each.value.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "PostgreSQL from ${each.key}."
}

resource "aws_vpc_security_group_egress_rule" "app_postgres" {
  for_each = aws_security_group.app

  security_group_id            = each.value.id
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "PostgreSQL to RDS."
}

resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name}-db" }
}

resource "aws_db_instance" "postgres" {
  identifier                  = "${local.name}-postgres"
  allocated_storage           = 20
  max_allocated_storage       = 50
  storage_type                = "gp3"
  storage_encrypted           = true
  engine                      = "postgres"
  engine_version              = var.db_engine_version
  instance_class              = var.db_instance_class
  db_name                     = "paper_trader"
  username                    = "paperadmin"
  manage_master_user_password = true
  backup_retention_period     = var.db_backup_retention_days
  copy_tags_to_snapshot       = true
  deletion_protection         = false
  skip_final_snapshot         = true
  publicly_accessible         = false
  multi_az                    = false
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  auto_minor_version_upgrade  = true
  apply_immediately           = false

  tags = { Name = "${local.name}-postgres" }
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.name}/database-url"
  description             = "Application database URL. Create its value outside Terraform."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "api_database_url" {
  name                    = "${local.name}/api-database-url"
  description             = "Read-only API database URL. Create its value outside Terraform."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "groq_api_key" {
  name                    = "${local.name}/groq-api-key"
  description             = "Groq API key. Create its value outside Terraform."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "agent_service_token" {
  name                    = "${local.name}/agent-service-token"
  description             = "Internal worker-to-agent token. Create its value outside Terraform."
  recovery_window_in_days = 0
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "agent_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      ]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role" "agent" {
  name               = "${local.name}-agent"
  assume_role_policy = data.aws_iam_policy_document.agent_assume.json
}

data "aws_iam_policy_document" "worker_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_url.arn, aws_secretsmanager_secret.agent_service_token.arn]
  }
}

data "aws_iam_policy_document" "api_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.api_database_url.arn]
  }
}

data "aws_iam_policy_document" "agent_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.groq_api_key.arn,
      aws_secretsmanager_secret.agent_service_token.arn,
    ]
  }
}

resource "aws_iam_role_policy" "worker_secrets" {
  name   = "read-required-secrets"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_secrets.json
}

resource "aws_iam_role_policy" "api_secrets" {
  name   = "read-required-secrets"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_secrets.json
}

resource "aws_iam_role_policy" "agent_secrets" {
  name   = "read-required-secrets"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent_secrets.json
}

resource "aws_budgets_budget" "monthly" {
  name              = "${local.name}-monthly"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
