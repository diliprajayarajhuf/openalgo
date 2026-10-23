variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "ami_id" {
  type        = string
  description = "Amazon Linux 2023 AMI ID"
}

variable "key_pair_name" {
  type        = string
  description = "Existing EC2 SSH key pair name"
}

variable "allowed_cidr" {
  type        = string
  description = "Your public IP in CIDR format, e.g. 203.0.113.10/32"
}
