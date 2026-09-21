terraform {
  backend "local" {
    path = "C:/Users/huuth/AppData/Local/patient-deid-pipeline/terraform-state/terraform.tfstate"
  }
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = "ap-southeast-2"
  profile = "terraform-patient-deid"
}

data "aws_caller_identity" "current" {}