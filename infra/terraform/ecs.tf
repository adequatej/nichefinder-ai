# ECS cluster, task definitions, and Fargate services for the three
# containers: api (FastAPI), worker (APScheduler cron), frontend (Next.js).
# Every task gets 0.25 vCPU and 512 MB, the smallest Fargate size.

locals {
  # Use the override image URI if given, otherwise the latest tag from the
  # ECR repos this stack creates.
  api_image      = var.api_image != "" ? var.api_image : "${aws_ecr_repository.api.repository_url}:latest"
  worker_image   = var.worker_image != "" ? var.worker_image : "${aws_ecr_repository.worker.repository_url}:latest"
  frontend_image = var.frontend_image != "" ? var.frontend_image : "${aws_ecr_repository.frontend.repository_url}:latest"

  database_url = "postgresql+asyncpg://${aws_db_instance.postgres.username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${aws_db_instance.postgres.db_name}"
  redis_url    = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0"

  # Environment shared by the api and worker containers.
  backend_environment = [
    { name = "DATABASE_URL", value = local.database_url },
    { name = "REDIS_URL", value = local.redis_url },
  ]

  backend_secrets = [
    { name = "YOUTUBE_API_KEY", valueFrom = aws_secretsmanager_secret.youtube_api_key.arn },
  ]
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  tags = {
    Environment = var.environment
  }
}

# Log groups with short retention. This is a demo stack, not an audit trail.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}-api"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}-worker"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${var.project_name}-frontend"
  retention_in_days = 7
}

# Execution role: what ECS itself needs to start the containers.
# Pull from ECR, write logs, and read the YouTube API key secret.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.project_name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "read_secret" {
  name = "${var.project_name}-read-youtube-secret"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.youtube_api_key.arn]
      }
    ]
  })
}

# Task definitions.

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.api_image
      essential = true

      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]

      environment = local.backend_environment
      secrets     = local.backend_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = local.worker_image
      essential = true

      environment = local.backend_environment
      secrets     = local.backend_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.project_name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = local.frontend_image
      essential = true

      portMappings = [
        { containerPort = 3000, protocol = "tcp" }
      ]

      # Both URLs point at the load balancer. The browser and the Next.js
      # server both reach the api through the same public hostname.
      environment = [
        { name = "NEXT_PUBLIC_API_URL", value = "http://${aws_lb.main.dns_name}" },
        { name = "API_URL_INTERNAL", value = "http://${aws_lb.main.dns_name}" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])
}

# Services. In demo mode the tasks sit in public subnets with public IPs so
# they can pull images and call the YouTube API without a NAT gateway.

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.service_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.demo_mode
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.service_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.demo_mode
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.project_name}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.service_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.demo_mode
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  depends_on = [aws_lb_listener.http]
}
