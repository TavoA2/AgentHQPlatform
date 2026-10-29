variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 size. t3.medium (2 vCPU, 4 GiB) fits both stacks and on-host builds."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "Encrypted gp3 root volume size."
  type        = number
  default     = 40
}

variable "repo_url" {
  description = "Git repository cloned on the instance (public HTTPS URL)."
  type        = string
  default     = "https://github.com/TavoA2/AgentHQPlatform.git"
}

variable "git_ref" {
  description = "Branch or tag checked out at bootstrap."
  type        = string
  default     = "main"
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget; alerts at 80% (actual) and 100% (forecast)."
  type        = number
  default     = 45
}

variable "alert_email" {
  description = "Email that receives budget alerts (AWS sends a confirmation first)."
  type        = string
}

variable "backup_retention_days" {
  description = "Days to keep database backups in S3."
  type        = number
  default     = 35
}
