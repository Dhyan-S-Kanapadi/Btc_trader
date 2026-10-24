# AWS foundation (Issue #31)

This Terraform stack creates the paper-trading AWS foundation only: a VPC, two private and two
public subnets, NAT egress, encrypted private RDS PostgreSQL with backups, secret containers, ECR,
least-privilege worker/API/agent roles, and a monthly AWS Budget alert. It does not deploy the
worker, API, frontend, AgentCore runtime, live trading, or any secret value.

Terraform is used rather than CDK because this stack is infrastructure-only and Terraform keeps the
provider resources and reviewable plan small. Terraform state must stay local or in an encrypted
remote backend you control; it is ignored by Git. No secret value is supplied to Terraform, so no
secret value enters state.

## Defaults and cost assumptions

- `us-east-1`, `10.31.0.0/16`, two Availability Zones, one NAT Gateway, `db.t4g.micro`, PostgreSQL
  16.15, 20 GiB encrypted storage, 7-day backups, and a USD 50 monthly budget are assumptions.
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
secret is separate; use it only to create minimally privileged application database roles during
Issue #32.

## Destroy

Stop later ECS/AgentCore resources first, then run:

```powershell
terraform destroy
```

AWS Budget email subscriptions may require a confirmation email before notifications are delivered.
