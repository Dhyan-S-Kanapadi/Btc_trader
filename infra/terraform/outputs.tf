output "ecr_repository_url" {
  description = "Repository for future worker, API, and AgentCore images."
  value       = aws_ecr_repository.app.repository_url
}

output "rds_endpoint" {
  description = "Private PostgreSQL endpoint; it contains no credentials."
  value       = aws_db_instance.postgres.address
}

output "rds_master_secret_arn" {
  description = "RDS-managed master-password secret ARN; its value is never in Terraform state."
  value       = one(aws_db_instance.postgres.master_user_secret[*].secret_arn)
}

output "application_secret_arns" {
  description = "Secret containers whose values must be set outside Terraform."
  value = {
    database_url        = aws_secretsmanager_secret.database_url.arn
    api_database_url    = aws_secretsmanager_secret.api_database_url.arn
    groq_api_key        = aws_secretsmanager_secret.groq_api_key.arn
    agent_service_token = aws_secretsmanager_secret.agent_service_token.arn
  }
}

output "security_group_ids" {
  description = "Private app security groups for later ECS and AgentCore runtime deployment."
  value       = { for name, group in aws_security_group.app : name => group.id }
}

output "iam_role_arns" {
  description = "Least-privilege roles for the worker, API, and AgentCore investigator."
  value = {
    worker = aws_iam_role.worker.arn
    api    = aws_iam_role.api.arn
    agent  = aws_iam_role.agent.arn
  }
}

output "ecs_cluster_name" {
  description = "ECS cluster containing the paper-only worker and read-only API services."
  value       = aws_ecs_cluster.main.name
}

output "agentcore_runtime_arn" {
  description = "AgentCore investigator runtime ARN; configure TRADER_AGENT_CLIENT__SERVICE_URL with it after apply."
  value       = aws_bedrockagentcore_agent_runtime.investigator.agent_runtime_arn
}

output "migration_task_definition_arn" {
  description = "Run this one-off Fargate task before starting the worker service."
  value       = aws_ecs_task_definition.migrate.arn
}

output "ecs_private_network" {
  description = "Private network values for the one-off migration Fargate task."
  value = {
    subnet_ids               = aws_subnet.private[*].id
    worker_security_group_id = aws_security_group.app["worker"].id
  }
}

output "api_url" {
  description = "Read-only HTTP API URL; place it behind HTTPS in the dashboard deployment."
  value       = "http://${aws_lb.api.dns_name}"
}
