terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket  = "us-east-1-openalgo"
    key     = "openalgo-state/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
}
# Automatically find the latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Generate an SSH key pair
resource "tls_private_key" "openalgo" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "openalgo" {
  key_name   = "openalgo-key"
  public_key = tls_private_key.openalgo.public_key_openssh
}

# Find the public IP of the machine running Terraform
data "http" "my_ip" {
  url = "https://checkip.amazonaws.com/"
}

# ── VPC ─────────────────────────────────────────────

resource "aws_vpc" "openalgo" {
  cidr_block           = "10.87.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "openalgo-vpc"
  }
}

resource "aws_subnet" "openalgo" {
  vpc_id                  = aws_vpc.openalgo.id
  cidr_block              = "10.87.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = {
    Name = "openalgo-subnet"
  }
}

resource "aws_internet_gateway" "openalgo" {
  vpc_id = aws_vpc.openalgo.id

  tags = {
    Name = "openalgo-igw"
  }
}

resource "aws_route_table" "openalgo" {
  vpc_id = aws_vpc.openalgo.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.openalgo.id
  }

  tags = {
    Name = "openalgo-rt"
  }
}

resource "aws_route_table_association" "openalgo" {
  subnet_id      = aws_subnet.openalgo.id
  route_table_id = aws_route_table.openalgo.id
}

# ── Security Group ──────────────────────────────────

resource "aws_security_group" "openalgo" {
  name        = "openalgo-sg"
  description = "SSH and OpenAlgo access"
  vpc_id      = aws_vpc.openalgo.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    description = "OpenAlgo Web"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    description = "OpenAlgo WebSocket"
    from_port   = 8765
    to_port     = 8765
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "openalgo-sg"
  }
}

# ── IAM Role ────────────────────────────────────────

resource "aws_iam_role" "openalgo" {
  name = "openalgo-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "openalgo" {
  name = "openalgo-ec2-policy"
  role = aws_iam_role.openalgo.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::us-east-1-openalgo/openalgo/openalgo.env"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = aws_ecr_repository.openalgo.arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "openalgo" {
  name = "openalgo-ec2-profile"
  role = aws_iam_role.openalgo.name
}

# ── ECR Repository ──────────────────────────────────

resource "aws_ecr_repository" "openalgo" {
  name                 = "openalgo"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "openalgo" {
  repository = aws_ecr_repository.openalgo.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 3 images"

        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 3
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ── EC2 ─────────────────────────────────────────────

resource "aws_instance" "openalgo" {
  ami                    = var.ami_id
  instance_type          = "t3.small"
  key_name               = var.key_pair_name
  subnet_id              = aws_subnet.openalgo.id
  vpc_security_group_ids = [aws_security_group.openalgo.id]
  iam_instance_profile   = aws_iam_instance_profile.openalgo.name

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    dnf install -y docker curl

    mkdir -p /usr/local/lib/docker/cli-plugins

    curl -fL --retry 3 \
      https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose

    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    systemctl enable --now docker
    usermod -aG docker ec2-user

    mkdir -p /home/ec2-user/openalgo
    chown ec2-user:ec2-user /home/ec2-user/openalgo
  EOF

  tags = {
    Name = "openalgo"
  }
}

# ── Elastic IP ──────────────────────────────────────

resource "aws_eip" "openalgo" {
  domain   = "vpc"
  instance = aws_instance.openalgo.id

  tags = {
    Name = "openalgo-eip"
  }
}

# ── Outputs ────────────────────────────────────────

output "elastic_ip" {
  value = aws_eip.openalgo.public_ip
}

output "instance_id" {
  value = aws_instance.openalgo.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.openalgo.repository_url
}
