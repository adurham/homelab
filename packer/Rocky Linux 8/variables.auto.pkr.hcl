variable "headless" {
  type    = string
  default = "true"
}
variable "version" {
  type    = string
  default = "8.7"
}
variable "vcenter_username" {
  type        = string
  description = "The username for the vcenter server"
  sensitive   = true
}
variable "vcenter_password" {
  type        = string
  description = "The password for the vcenter server"
  sensitive   = true
}
variable "ssh_username" {
  type        = string
  description = "The username for the SSH user"
  sensitive   = true
}
variable "ssh_password" {
  type        = string
  description = "The password for the SSH user"
  sensitive   = true
}
variable "ssh_publickey" {
  type        = string
  description = "The publickey for the SSH user"
  sensitive   = true
}
variable "hashed_admin_password" {
  type        = string
  description = "SHA512 of the password for the Admin user"
  sensitive   = true
}
variable "hashed_packer_password" {
  type        = string
  description = "SHA512 of the password for the Packer user"
  sensitive   = true
}
variable "hashed_grub_password" {
  type        = string
  description = "SHA512 of the grub bootloader password"
  sensitive   = true
}