#!/bin/sh

curl https://us-west-2.cloudconformity.com/v1/policies \
  | jq '[.Resources[] | select(.Type == "AWS::IAM::ManagedPolicy") | { name: .Properties.ManagedPolicyName, document: .Properties.PolicyDocument }]' \
  > iam-policies.json
