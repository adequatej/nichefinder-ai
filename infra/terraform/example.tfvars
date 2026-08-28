# Example values only. Copy this file to something like demo.tfvars and fill
# in real values there. Real tfvars files never get committed; .gitignore
# excludes *.tfvars except this example file.

region          = "us-east-1"
project_name    = "nichefinder"
environment     = "demo"
demo_mode       = true
db_password     = "change-me-strong-password"
youtube_api_key = "change-me-youtube-api-key"

# Leave the image variables empty to use the latest tag from the ECR repos
# this stack creates, or pin exact image URIs here.
api_image      = ""
worker_image   = ""
frontend_image = ""
