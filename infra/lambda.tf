# ============================================================
# START / STOP LAMBDA
# ============================================================
# Runs custom/lambda (built by deploy.yml into the openalgo ECR repo under
# lambda-* tags). Two schedules drive it:
#   start  08:55 IST Mon-Fri (the function skips NSE holidays)
#   stop   16:30 IST every day

variable "lambda_image_tag" {
  type        = string
  default     = "latest"
  description = "Tag suffix of the custom Lambda image (lambda-<tag>)"
}

locals {
  lambda_name = "openalgo-custom"
}

resource "aws_iam_role" "lambda" {
  name = "openalgo-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "openalgo-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${local.lambda_name}:*"
      },
      {
        Effect = "Allow"

        # DescribeInstances does not support resource-level permissions.
        Action = [
          "ec2:DescribeInstances"
        ]

        Resource = "*"
      },
      {
        Effect = "Allow"

        Action = [
          "ec2:StartInstances",
          "ec2:StopInstances"
        ]

        Resource = aws_instance.openalgo.arn
      }
    ]
  })
}

# Lambda pulls its image from the openalgo repo.
resource "aws_ecr_repository_policy" "openalgo_lambda_pull" {
  repository = aws_ecr_repository.openalgo.name

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "LambdaPull"
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "custom" {
  function_name = local.lambda_name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.openalgo.repository_url}:lambda-${var.lambda_image_tag}"
  architectures = ["x86_64"]
  timeout       = 60
  memory_size   = 512

  environment {
    variables = {
      OPENALGO_INSTANCE_ID = aws_instance.openalgo.id
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_ecr_repository_policy.openalgo_lambda_pull
  ]
}

# ============================================================
# SCHEDULES
# ============================================================

resource "aws_iam_role" "scheduler" {
  name = "openalgo-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "scheduler.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "openalgo-scheduler-policy"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "lambda:InvokeFunction"
        ]

        Resource = aws_lambda_function.custom.arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "openalgo_start" {
  name                         = "openalgo-start"
  schedule_expression          = "cron(55 8 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.custom.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "start" })
  }
}

resource "aws_scheduler_schedule" "openalgo_stop" {
  name                         = "openalgo-stop"
  schedule_expression          = "cron(30 16 * * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.custom.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "stop" })
  }
}

output "lambda_function_name" {
  value = aws_lambda_function.custom.function_name
}
