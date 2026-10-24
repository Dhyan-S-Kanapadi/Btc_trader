# Issue #32 — Deploy worker and API on ECS Fargate

Status: Terraform definitions verified; no AWS apply, image push, secret value, migration run, or
ECS task has been started.

The stack adds a Fargate cluster, a one-task worker service, a read-only API service behind an
application load balancer, scoped execution roles for Secrets Manager injection, a one-off migration
task definition, container/load-balancer health checks, and CloudWatch Logs. The worker remains
paper-only and retains its database advisory lock; an ECS restart therefore cannot create duplicate
orders by itself.

Before deployment, CI must push an immutable image to ECR, an operator must set the database secret
values outside Terraform, and the migration task must exit successfully before services are created.
The 48-hour run, forced-restart recovery, and live API reachability are AWS operational acceptance
checks, not claims made by this definition-only change.
