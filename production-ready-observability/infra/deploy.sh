#!/usr/bin/env bash
# ============================================================================
# deploy.sh
#
# Deploys the fraud detection infrastructure and automatically grants the
# deploying user RBAC access to Cosmos DB and Azure AI Search.
#
# Usage:
#   ./infra/deploy.sh <RESOURCE_GROUP_NAME> [LOCATION]
#
# Examples:
#   ./infra/deploy.sh my-rg
#   ./infra/deploy.sh my-rg northcentralus
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
# ============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <RESOURCE_GROUP_NAME> [LOCATION]"
  exit 1
fi

RESOURCE_GROUP="$1"
LOCATION="${2:-northcentralus}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🔍 Resolving deployer principal ID..."
DEPLOYER_PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
echo "   Principal ID: ${DEPLOYER_PRINCIPAL_ID}"

echo ""
echo "📦 Creating resource group: ${RESOURCE_GROUP} in ${LOCATION}..."
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

echo ""
echo "🚀 Deploying infrastructure..."
az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${SCRIPT_DIR}/setup.bicep" \
  --parameters "@${SCRIPT_DIR}/setup.parameters.json" \
  --parameters deployerPrincipalId="${DEPLOYER_PRINCIPAL_ID}"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "  1. Run: ./infra/setup-env.sh ${RESOURCE_GROUP}"
echo "  2. Run: ./data/seed_data.sh"
