# Run Terraform from this nac/ directory so yaml_directories = ["."] resolves
# to the directory containing both main.tf and nac.yaml. From the lab root, use:
# terraform -chdir=<lab>/nac <command>

module "iosxe" {
  source           = "netascode/nac-iosxe/iosxe"
  version          = "0.1.0"
  yaml_directories = ["."]
}

provider "iosxe" {
  # The CiscoDevNet/iosxe provider reads IOSXE_URL, IOSXE_USERNAME, and
  # IOSXE_PASSWORD (or its documented IOSXE_* environment variables).
  # Do not put lab URLs, usernames, or passwords in Terraform files.
  #
  # LAB ONLY: insecure disables TLS certificate verification; acceptable only
  # for throwaway lab gear with self-signed certificates. Never use this for
  # production NaC.
  insecure = true
}
