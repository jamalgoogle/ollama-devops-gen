#!/usr/bin/env bash
# create_vpc.sh - create a VPC with public + private subnets (best practices)
# Needs: AWS CLI v2 and a logged-in profile.   Run: ./create_vpc.sh
# WARNING: the NAT Gateway costs money every hour. Delete it when you finish.

set -euo pipefail          # -e stop on error, -u stop on unset variable, pipefail catch errors in pipes

# ---------- Settings (change here only) ----------
REGION="${AWS_REGION:-us-east-1}"     # AWS region
NAME="${PROJECT_NAME:-demo}"          # prefix for all names
VPC_CIDR="10.0.0.0/16"                # whole network: 65,536 IPs
PUBLIC_CIDRS=("10.0.1.0/24" "10.0.2.0/24")     # 2 public subnets (2 AZs)
PRIVATE_CIDRS=("10.0.11.0/24" "10.0.12.0/24")  # 2 private subnets (2 AZs)
STATE_FILE="vpc_state.env"            # we save all IDs here for cleanup

# ---------- Helpers ----------
log()  { echo "[$(date +%H:%M:%S)] $*"; }                    # print a message with time
fail() { echo "❌ ERROR on line $1. Run ./cleanup_vpc.sh to remove partial resources." >&2; }
trap 'fail $LINENO' ERR                                      # call fail() if any command fails
aws_() { aws --region "$REGION" "$@"; }                      # always use the same region

# Build the --tag-specifications text. $1 = resource type, $2 = Name tag
tags() {
  echo "ResourceType=$1,Tags=[{Key=Name,Value=$NAME-$2},{Key=Project,Value=$NAME},{Key=ManagedBy,Value=script}]"
}

command -v aws >/dev/null || { echo "AWS CLI not found"; exit 1; }   # check tools first
aws_ sts get-caller-identity >/dev/null                              # check login works

# Pick the first 2 availability zones of the region
mapfile -t AZS < <(aws_ ec2 describe-availability-zones \
  --query 'AvailabilityZones[?State==`available`].ZoneName' --output text | tr '\t' '\n' | head -2)

# ---------- 1. VPC ----------
log "Creating VPC $VPC_CIDR"
VPC_ID=$(aws_ ec2 create-vpc --cidr-block "$VPC_CIDR" \
  --tag-specifications "$(tags vpc vpc)" --query 'Vpc.VpcId' --output text)
aws_ ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support  '{"Value":true}'
aws_ ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}'
echo "VPC_ID=$VPC_ID" > "$STATE_FILE"                    # save the ID

# ---------- 2. Internet Gateway (door to the internet) ----------
log "Creating Internet Gateway"
IGW_ID=$(aws_ ec2 create-internet-gateway \
  --tag-specifications "$(tags internet-gateway igw)" \
  --query 'InternetGateway.InternetGatewayId' --output text)
aws_ ec2 attach-internet-gateway --vpc-id "$VPC_ID" --internet-gateway-id "$IGW_ID"
echo "IGW_ID=$IGW_ID" >> "$STATE_FILE"

# ---------- 3. Subnets ----------
PUBLIC_IDS=(); PRIVATE_IDS=()
for i in 0 1; do
  log "Creating subnets in ${AZS[$i]}"
  PUB=$(aws_ ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "${PUBLIC_CIDRS[$i]}" \
    --availability-zone "${AZS[$i]}" --tag-specifications "$(tags subnet public-$((i+1)))" \
    --query 'Subnet.SubnetId' --output text)
  aws_ ec2 modify-subnet-attribute --subnet-id "$PUB" --map-public-ip-on-launch  # public IP for new VMs
  PRV=$(aws_ ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "${PRIVATE_CIDRS[$i]}" \
    --availability-zone "${AZS[$i]}" --tag-specifications "$(tags subnet private-$((i+1)))" \
    --query 'Subnet.SubnetId' --output text)
  PUBLIC_IDS+=("$PUB"); PRIVATE_IDS+=("$PRV")
done
echo "PUBLIC_IDS=\"${PUBLIC_IDS[*]}\"" >> "$STATE_FILE"
echo "PRIVATE_IDS=\"${PRIVATE_IDS[*]}\"" >> "$STATE_FILE"

# ---------- 4. NAT Gateway (private subnets go out, nobody comes in) ----------
log "Creating Elastic IP + NAT Gateway (takes 1-2 minutes)"
EIP_ALLOC=$(aws_ ec2 allocate-address --domain vpc \
  --tag-specifications "$(tags elastic-ip nat-eip)" --query 'AllocationId' --output text)
NAT_ID=$(aws_ ec2 create-nat-gateway --subnet-id "${PUBLIC_IDS[0]}" --allocation-id "$EIP_ALLOC" \
  --tag-specifications "$(tags natgateway nat)" --query 'NatGateway.NatGatewayId' --output text)
echo "EIP_ALLOC=$EIP_ALLOC" >> "$STATE_FILE"; echo "NAT_ID=$NAT_ID" >> "$STATE_FILE"
aws_ ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_ID"   # wait until ready

# ---------- 5. Route tables ----------
log "Creating route tables"
PUB_RT=$(aws_ ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications "$(tags route-table public-rt)" --query 'RouteTable.RouteTableId' --output text)
aws_ ec2 create-route --route-table-id "$PUB_RT" --destination-cidr-block 0.0.0.0/0 \
  --gateway-id "$IGW_ID" >/dev/null                  # public: internet traffic -> IGW
PRV_RT=$(aws_ ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications "$(tags route-table private-rt)" --query 'RouteTable.RouteTableId' --output text)
aws_ ec2 create-route --route-table-id "$PRV_RT" --destination-cidr-block 0.0.0.0/0 \
  --nat-gateway-id "$NAT_ID" >/dev/null              # private: internet traffic -> NAT
for id in "${PUBLIC_IDS[@]}";  do aws_ ec2 associate-route-table --route-table-id "$PUB_RT" --subnet-id "$id" >/dev/null; done
for id in "${PRIVATE_IDS[@]}"; do aws_ ec2 associate-route-table --route-table-id "$PRV_RT" --subnet-id "$id" >/dev/null; done
echo "PUB_RT=$PUB_RT" >> "$STATE_FILE"; echo "PRV_RT=$PRV_RT" >> "$STATE_FILE"

# ---------- Done ----------
log "✅ Done. VPC=$VPC_ID  public=${PUBLIC_IDS[*]}  private=${PRIVATE_IDS[*]}"
log "IDs are saved in $STATE_FILE. Remove everything with: ./cleanup_vpc.sh"
