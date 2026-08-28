# Container image repositories. force_delete lets terraform destroy remove
# a repo that still holds images, which a short-lived demo needs.

resource "aws_ecr_repository" "api" {
  name         = "${var.project_name}-api"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name         = "${var.project_name}-worker"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name         = "${var.project_name}-frontend"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
