locals {
  ip_dashed = replace(aws_eip.app.public_ip, ".", "-")
}

output "public_ip" {
  value = aws_eip.app.public_ip
}

output "instance_id" {
  value = aws_instance.app.id
}

output "suggested_hq_domain" {
  description = "Use until you own a domain (sslip.io resolves it to the Elastic IP)."
  value       = "hq.${local.ip_dashed}.sslip.io"
}

output "suggested_demo_domain" {
  value = "demo.${local.ip_dashed}.sslip.io"
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "connect" {
  description = "Open a shell on the instance (no SSH needed)."
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.region}"
}
