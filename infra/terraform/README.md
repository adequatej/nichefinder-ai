# Terraform stack

Deploy-ready AWS infrastructure for NicheFinder AI. It mirrors the docker-compose setup:

- VPC with two public subnets (plus private subnets and a NAT gateway when `demo_mode = false`)
- Three ECR repositories for the api, worker, and frontend images
- RDS Postgres 16 on db.t4g.micro, not publicly accessible
- ElastiCache Redis 7, single cache.t4g.micro node
- ECS Fargate cluster with three services: api (port 8000), worker (no ports), frontend (port 3000)
- Application load balancer routing /api/* to FastAPI and everything else to Next.js
- Secrets Manager entry for the YouTube API key

## Cost warning

The ALB, RDS instance, and ElastiCache node bill by the hour from the moment they exist, whether or not you use them. With `demo_mode = false` a NAT gateway bills hourly too. Deploy and destroy on the same day. A one-day demo run costs roughly 3 to 5 US dollars. Forgetting to destroy costs roughly 60 to 90 dollars a month.

Demo mode (the default) puts the containers in public subnets with public IPs, which removes the NAT gateway cost. That is fine for a short-lived demo but not a production layout. Set `demo_mode = false` for private subnets behind a NAT.

## Usage

Copy `example.tfvars` to a real tfvars file first (for example `demo.tfvars`) and fill in real values. Real tfvars files never get committed.

```
terraform init
terraform plan -var-file=demo.tfvars
terraform destroy -var-file=demo.tfvars
```

Note: `terraform plan` talks to AWS to read account details, so it needs working AWS credentials even though it deploys nothing. `terraform validate` works without credentials.
