# Postgres database. Never publicly accessible. Only the ECS tasks can
# reach port 5432. Note: the docker-compose project uses the pgvector image;
# on RDS the pgvector extension ships with Postgres 16 and is enabled with
# CREATE EXTENSION vector after first connect (the app migration does this).

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db"
  subnet_ids = local.service_subnet_ids

  tags = {
    Name = "${var.project_name}-db"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds"
  description = "Postgres access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-rds"
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "nichefinder"
  username = "nichefinder"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # A demo teardown should not leave a snapshot behind.
  skip_final_snapshot       = var.demo_mode
  final_snapshot_identifier = "${var.project_name}-final"

  tags = {
    Name        = "${var.project_name}-db"
    Environment = var.environment
  }
}
