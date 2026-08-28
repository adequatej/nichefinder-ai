output "alb_dns_name" {
  description = "Public hostname of the load balancer. The app lives at http:// this address."
  value       = aws_lb.main.dns_name
}

output "ecr_api_repository_url" {
  description = "Push the api image here."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repository_url" {
  description = "Push the worker image here."
  value       = aws_ecr_repository.worker.repository_url
}

output "ecr_frontend_repository_url" {
  description = "Push the frontend image here."
  value       = aws_ecr_repository.frontend.repository_url
}

output "rds_endpoint" {
  description = "Postgres endpoint (host and port)."
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "Redis endpoint address."
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}
