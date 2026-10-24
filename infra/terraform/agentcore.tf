locals {
  agent_image = "${aws_ecr_repository.app.repository_url}:${var.agent_image_tag}"
}

resource "aws_bedrockagentcore_agent_runtime" "investigator" {
  agent_runtime_name = "${local.name}-investigator"
  description        = "Paper-trading investigator: read-only evidence and Groq vetoes only."
  role_arn           = aws_iam_role.agent.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.agent_image
    }
  }

  environment_variables = {
    GROQ_SECRET_ARN                     = aws_secretsmanager_secret.groq_api_key.arn
    TRADER_AGENT__GROQ_MODEL            = var.groq_model
    TRADER_AGENT_TOOLS__API_BASE_URL    = "http://${aws_lb.api.dns_name}"
    TRADER_AGENT_TOOLS__MAX_RETRIES     = "1"
    TRADER_AGENT_TOOLS__TIMEOUT_SECONDS = "5"
    TRADER_AGENT__GROQ_TIMEOUT_SECONDS  = "10"
    TRADER_AGENT__WALL_CLOCK_SECONDS    = "15"
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = aws_subnet.private[*].id
      security_groups = [aws_security_group.app["agent"].id]
    }
  }

  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 28800
  }
}

data "aws_iam_policy_document" "worker_agentcore" {
  statement {
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.investigator.agent_runtime_arn]
  }
}

resource "aws_iam_role_policy" "worker_agentcore" {
  name   = "invoke-investigator-runtime"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_agentcore.json
}
