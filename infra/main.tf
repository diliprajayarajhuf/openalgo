
terraform {
  required_version = ">= 1.5.0"

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

# ============================================================
# PROVIDER
# ============================================================

provider "aws" {
  region = var.aws_region
}

# ============================================================
# VARIABLES
# ============================================================

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "key_pair_name" {
  type        = string
  description = "Name of an existing EC2 SSH key pair"
}

variable "allowed_cidr" {
  type        = string
  description = "CIDR permitted to access SSH and OpenAlgo"

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0))
    error_message = "Provide a valid CIDR, such as 203.0.113.10/32."
  }
}

# ============================================================
# AMAZON LINUX 2023 AMI
# ============================================================

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

# ============================================================
# NETWORKING
# ============================================================

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
  map_public_ip_on_launch = false

  tags = {
    Name = "openalgo-public-subnet"
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
    Name = "openalgo-public-route-table"
  }
}

resource "aws_route_table_association" "openalgo" {
  subnet_id      = aws_subnet.openalgo.id
  route_table_id = aws_route_table.openalgo.id
}

# ============================================================
# SECURITY GROUP
# ============================================================

resource "aws_security_group" "openalgo" {
  name        = "openalgo-sg"
  description = "SSH and OpenAlgo access"
  vpc_id      = aws_vpc.openalgo.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "OpenAlgo Web"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "OpenAlgo WebSocket"
    from_port   = 8765
    to_port     = 8765
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "openalgo-sg"
  }
}

# ============================================================
# ECR
# ============================================================

resource "aws_ecr_repository" "openalgo" {
  name                 = "openalgo"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "openalgo"
  }
}

resource "aws_ecr_lifecycle_policy" "openalgo" {
  repository = aws_ecr_repository.openalgo.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the latest 3 images"

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

# ============================================================
# EC2 IAM ROLE
# ============================================================

resource "aws_iam_role" "openalgo" {
  name = "openalgo-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
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

        Resource = [
          "arn:aws:s3:::us-east-1-openalgo/openalgo/openalgo.env"
        ]
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

# ============================================================
# EC2 INSTANCE
# ============================================================

resource "aws_instance" "openalgo" {
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "t3.small"

  key_name = var.key_pair_name

  subnet_id              = aws_subnet.openalgo.id
  vpc_security_group_ids = [aws_security_group.openalgo.id]

  iam_instance_profile = aws_iam_instance_profile.openalgo.name

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    dnf install -y docker curl awscli-2

    mkdir -p /usr/local/lib/docker/cli-plugins

    curl -fL --retry 3 \
      https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose

    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    systemctl enable --now docker

    usermod -aG docker ec2-user

    mkdir -p /home/ec2-user/openalgo

    chown -R ec2-user:ec2-user /home/ec2-user/openalgo
  EOF

  tags = {
    Name = "openalgo"
  }

  depends_on = [
    aws_route_table_association.openalgo
  ]
}

# ============================================================
# ELASTIC IP
# ============================================================

resource "aws_eip" "openalgo" {
  domain   = "vpc"
  instance = aws_instance.openalgo.id

  tags = {
    Name = "openalgo-eip"
  }

  depends_on = [
    aws_internet_gateway.openalgo
  ]
}

# ============================================================
# OUTPUTS
# ============================================================

output "instance_id" {
  value = aws_instance.openalgo.id
}

output "elastic_ip" {
  value = aws_eip.openalgo.public_ip
}

output "ecr_repository_url" {
  value = aws_ecr_repository.openalgo.repository_url
}

output "ssh_command" {
  value = "ssh -i YOUR_PRIVATE_KEY.pem ec2-user@${aws_eip.openalgo.public_ip}"
}

output "openalgo_url" {
  value = "http://${aws_eip.openalgo.public_ip}:5000"
}
