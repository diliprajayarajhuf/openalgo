
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

  # Port 80 answers the Let's
  # Encrypt challenge. Caddy serves OpenAlgo over https on 5000; the app
  # and its WebSocket (8765) are bound to the instance only.
  ingress {
    description = "HTTP for certificate issuance and redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "OpenAlgo over HTTPS on 5000"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
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

  # Every deploy pushes sha-<commit> and moves latest onto it. Keep the last
  # five builds for rollback and drop anything left untagged.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 2
        description  = "Keep the last 5 commit builds"

        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }

        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 3
        description  = "Keep the last 5 custom Lambda builds"

        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["lambda-sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }

        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"

        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
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
          "s3:GetObject",
          "s3:PutObject"
        ]

        Resource = [
          "arn:aws:s3:::us-east-1-openalgo/orders/*"
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

    # curl-minimal and awscli-2 ship with AL2023; installing full curl
    # conflicts with curl-minimal and would abort this script under set -e.
    dnf install -y docker

    # t3.small has 2 GB RAM; swap keeps an image pull or a strategy run
    # from getting the OpenAlgo container OOM-killed.
    if [ ! -f /swapfile ]; then
      dd if=/dev/zero of=/swapfile bs=1M count=2048
      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      echo "/swapfile swap swap defaults 0 0" >> /etc/fstab
    fi

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
  value = "https://${replace(aws_eip.openalgo.public_ip, ".", "-")}.sslip.io:5000"
}
