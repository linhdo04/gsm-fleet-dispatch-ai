variable "project_id" {
  type        = string
  description = "Google Cloud project ID"
}

variable "network_name" {
  type        = string
  description = "VPC network name"
  default     = "gcp-custom-vpc"
}

variable "subnets" {
  type = list(object({
    name          = string
    ip_cidr_range = string
    region        = string
  }))
  description = "List of subnets to create in the VPC network"
  default     = []
}
