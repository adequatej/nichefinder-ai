# The YouTube API key lives in Secrets Manager and is injected into the
# api and worker containers at start. It never appears in a task definition
# in plain text.

resource "aws_secretsmanager_secret" "youtube_api_key" {
  name = "${var.project_name}-youtube-api-key"

  # Zero recovery window so terraform destroy deletes it immediately.
  # Without this, the name stays reserved for up to 30 days.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "youtube_api_key" {
  secret_id     = aws_secretsmanager_secret.youtube_api_key.id
  secret_string = var.youtube_api_key
}
