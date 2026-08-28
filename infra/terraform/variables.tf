variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for every resource in this stack."
  type        = string
  default     = "nichefinder"
}

variable "environment" {
  description = "Environment label used in tags."
  type        = string
  default     = "demo"
}

variable "db_password" {
  description = "Master password for the Postgres database. Avoid characters that need URL encoding, because the password is placed inside DATABASE_URL."
  type        = string
  sensitive   = true
}

variable "youtube_api_key" {
  description = "YouTube Data API key. Stored in Secrets Manager and injected into the api and worker containers."
  type        = string
  sensitive   = true
}

variable "api_image" {
  description = "Full image URI for the api container. Empty string means use the latest tag from the ECR repo this stack creates."
  type        = string
  default     = ""
}

variable "worker_image" {
  description = "Full image URI for the worker container. Empty string means use the latest tag from the ECR repo this stack creates."
  type        = string
  default     = ""
}

variable "frontend_image" {
  description = "Full image URI for the frontend container. Empty string means use the latest tag from the ECR repo this stack creates."
  type        = string
  default     = ""
}

variable "demo_mode" {
  description = "Demo mode uses public subnets with public IPs and no NAT gateway to keep a short-lived deploy cheap. Set false for a production layout with private subnets and a NAT gateway."
  type        = bool
  default     = true
}
