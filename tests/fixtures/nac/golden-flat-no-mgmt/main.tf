# Run Terraform from this nac/ directory so yaml_files = ["nac.yaml"] resolves
# to nac.yaml beside main.tf. From the lab root, use:
# terraform -chdir=<lab>/nac <command>
#
# NOTE: the module is pointed at the single nac.yaml via yaml_files. Do NOT use
# yaml_directories = ["."] here: it recurses this directory (and .terraform/)
# and ingests the Ansible/informational YAML, which breaks the module's
# yaml_merge (top-level sequences are not valid NaC model fragments).
#
# nac-iosxe 1.0.0 configures the IOS-XE provider inside the module from each
# device host in nac.yaml. Transport is NETCONF over SSH on TCP 830. Provider
# 1.0.0 removed RESTCONF and the URL-style provider attribute.
# Do not add a root iosxe provider block; module resources use the provider
# configuration inside the module.
#
# Set IOSXE_USERNAME and IOSXE_PASSWORD in the environment. Do not put lab
# URLs, usernames, or passwords in Terraform files. The provider insecure
# default is true (skip SSH host-key checks) and is acceptable only for
# throwaway lab gear.

module "iosxe" {
  source     = "netascode/nac-iosxe/iosxe"
  version    = "1.0.0"
  yaml_files = ["nac.yaml"]
}
