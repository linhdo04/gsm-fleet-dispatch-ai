variable "project_id" {
  type        = string
  description = "Google Cloud project ID"
}

variable "instance_name" {
  type        = string
  description = "VM instance name"
}

variable "machine_type" {
  type        = string
  description = "VM machine type"
  default     = "e2-medium"
}

variable "zone" {
  type        = string
  description = "Zone where the VM will be created"
  default     = "asia-southeast1-a"
}

variable "subnet_id" {
  type        = string
  description = "ID of the Subnet to which the VM will be attached"
}

variable "boot_image" {
  type        = string
  description = "Operating system to use"
  default     = "ubuntu-os-cloud/ubuntu-2204-lts"
}

variable "boot_disk_size" {
  type        = number
  description = "Boot disk size in GB"
  default     = 20
}

variable "data_disk_size" {
  type        = number
  description = "Size in GB of the persistent data disk; set to 0 to disable"
  default     = 0
}

variable "data_disk_type" {
  type        = string
  description = "Persistent data disk type"
  default     = "pd-balanced"
}

variable "network_tags" {
  type        = list(string)
  description = "Network tags to apply to the VM"
  default     = []
}

variable "startup_script" {
  type        = string
  description = "Script to run automatically when the VM starts for the first time"
  default     = ""
}

variable "enable_public_ip" {
  type        = bool
  description = "Enable/disable public IP for the VM"
  default     = false
}
