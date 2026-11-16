#!/usr/bin/env bash
# cleanup_vpc.sh - delete everything created by create_vpc.sh (stops NAT cost)
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
source vpc_state.env                                   # load the saved IDs
aws_() { aws --region "$REGION" "$@"; }                # same region helper

# Order matters: delete the things that depend on others FIRST.
if [ -n "${NAT_ID:-}" ]; then                          # 1. NAT Gateway
  aws_ ec2 delete-nat-gateway --nat-gateway-id "$NAT_ID" >/dev/null
  aws_ ec2 wait nat-gateway-deleted --nat-gateway-ids "$NAT_ID"
fi
[ -n "${EIP_ALLOC:-}" ] && aws_ ec2 release-address --allocation-id "$EIP_ALLOC"   # 2. Elastic IP
for rt in "${PUB_RT:-}" "${PRV_RT:-}"; do              # 3. Route tables
  [ -z "$rt" ] && continue
  for assoc in $(aws_ ec2 describe-route-tables --route-table-ids "$rt" \
      --query 'RouteTables[0].Associations[].RouteTableAssociationId' --output text); do
    aws_ ec2 disassociate-route-table --association-id "$assoc"   # remove the link first
  done
  aws_ ec2 delete-route-table --route-table-id "$rt"
done
for id in ${PUBLIC_IDS:-} ${PRIVATE_IDS:-}; do aws_ ec2 delete-subnet --subnet-id "$id"; done  # 4. Subnets
if [ -n "${IGW_ID:-}" ]; then                          # 5. Internet Gateway
  aws_ ec2 detach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
  aws_ ec2 delete-internet-gateway --internet-gateway-id "$IGW_ID"
fi
aws_ ec2 delete-vpc --vpc-id "$VPC_ID"                 # 6. VPC last
rm -f vpc_state.env
echo "✅ All deleted."
