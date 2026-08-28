# Network layout. Demo mode keeps everything in public subnets so no NAT
# gateway is needed. Non-demo mode adds private subnets behind a single NAT.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "${var.project_name}-vpc"
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-${count.index}"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private networking, only created when demo_mode is false.

resource "aws_subnet" "private" {
  count = var.demo_mode ? 0 : 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1${count.index}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.project_name}-private-${count.index}"
  }
}

resource "aws_eip" "nat" {
  count = var.demo_mode ? 0 : 1

  domain = "vpc"

  tags = {
    Name = "${var.project_name}-nat"
  }
}

resource "aws_nat_gateway" "main" {
  count = var.demo_mode ? 0 : 1

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${var.project_name}-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  count = var.demo_mode ? 0 : 1

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[0].id
  }

  tags = {
    Name = "${var.project_name}-private"
  }
}

resource "aws_route_table_association" "private" {
  count = var.demo_mode ? 0 : 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

locals {
  # Where the containers and databases live. Public in demo mode, private otherwise.
  service_subnet_ids = var.demo_mode ? aws_subnet.public[*].id : aws_subnet.private[*].id
}
