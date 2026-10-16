terraform {
  required_version = ">= 1.9.0"

  required_providers {
    iosxe = {
      source  = "CiscoDevNet/iosxe"
      version = "1.1.1"
    }
  }
}
