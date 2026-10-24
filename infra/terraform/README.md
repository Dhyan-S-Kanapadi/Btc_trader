# AWS foundation and ECS deployment definition (Issues #31 and #32)

This Terraform stack creates the paper-trading AWS foundation and ECS deployment definition: a VPC,
two private and two public subnets, NAT egress, encrypted private RDS PostgreSQL with backups,
secret containers, ECR, least-privilege roles, CloudWatch log groups, an ECS cluster, Fargate task
definitions, and a read-only API load balancer. It does not build images, set secret values, deploy
the frontend or AgentCore runtime, or enable live trading.

Terraform is used rather than CDK because this stack is infrastructure-only and Terraform keeps the
provider resources and reviewable plan small. Terraform state must stay local or in an encrypted
remote backend you control; it is ignored by Git. No secret value is supplied to Terraform, so no
secret value enters state.

## Defaults and cost assumptions

- `us-east-1`, `10.31.0.0/16`, two Availability Zones, one NAT Gateway, `db.t4g.micro`, PostgreSQL
  16.15, 20 GiB encrypted storage, 7-day backups, a USD 50 monthly budget, 30-day log retention,
  256 CPU units/512 MiB per Fargate task, and a public HTTP API load balancer are assumptions.
- One NAT Gateway and one single-AZ database reduce early paper-trading cost. They are not
  high-availability production architecture. At the currently published USD 0.045 NAT Gateway
  hourly rate, the gateway alone is about USD 32.85 for a 730-hour month before data processing,
  RDS, storage, and public IPv4 charges.
- The budget sends a forecast alert at 80% and an actual-cost alert at 100%. It is an alert, not a
  hard spend limit.
- `destroy` intentionally deletes the database without a final snapshot. Take an explicit snapshot
  first if the paper-trading data matters.

## Apply

Install Terraform 1.6+ and authenticate the AWS CLI to the intended account and Region. Copy the
example variables file without committing it:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan
terraform apply
```

After apply, set values for the four application secrets directly in AWS Secrets Manager. Do not
put a secret in `terraform.tfvars`, source code, logs, or Terraform state. The RDS-generated master
secret is separate; use it only to create minimally privileged application database roles.

## ECS deployment order

Issue #32 consumes an immutable image tag built and pushed to the ECR repository by CI. Set
`app_image_tag` to that tag in the ignored `terraform.tfvars`; never use a mutable tag such as
`latest`. Before creating the ECS services, populate `database-url` and `api-database-url` with
the application database URLs. The API secret must use the read-only database role.

Use a targeted task-definition apply to register the one-off migration task before creating the
services, then run it once, wait for exit code zero in CloudWatch Logs, and apply the full stack:

```powershell
terraform apply -target=aws_ecs_cluster.main -target=aws_ecs_task_definition.migrate
aws ecs run-task --cluster <ecs_cluster_name> --launch-type FARGATE --task-definition <migration_task_definition_arn> --network-configuration "awsvpcConfiguration={subnets=[<private-subnet-id>],securityGroups=[<worker-security-group-id>],assignPublicIp=DISABLED}"
terraform apply
```

The worker service has desired count one and also holds the PostgreSQL advisory lock, so a forced
restart does not create duplicate paper orders. The API task is private behind the load balancer;
`/health` is checked by both its container and the load balancer. The load balancer is HTTP only in
this issue; place it behind the HTTPS dashboard delivery in Issue #33 before public use.

## Destroy

Stop later ECS/AgentCore resources first, then run:

```powershell
terraform destroy
```

AWS Budget email subscriptions may require a confirmation email before notifications are delivered.
