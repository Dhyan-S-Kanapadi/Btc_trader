# Issue #31 — Infrastructure as code base

Status: Terraform definition verified; AWS apply is intentionally pending a real budget-alert recipient.

Terraform defines the paper-only AWS foundation: VPC/subnets, NAT egress, encrypted private RDS
PostgreSQL with backups, Secrets Manager containers, ECR, scoped worker/API/agent IAM roles, and a
monthly budget alert. Secret values are deliberately excluded from Terraform and its state.

The next deployment issues consume this stack: #32 adds ECS task definitions, #33 deploys the
static dashboard, and #34 deploys the AgentCore investigator. No worker, broker, risk setting, or
live-trading capability changes in this issue.
