#!/bin/bash
# Dedicated paywall flag management — the ONLY way to change PAYWALL_ENABLED.
# Usage: ./scripts/set_paywall.sh on|off
#
# Changes ONLY PAYWALL_ENABLED in .env. Does NOT restart/rebuild anything.
# Logs every change with timestamp to logs/paywall_flag.log.
# Deploy commands must NEVER touch PAYWALL_ENABLED — use this script.

set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env"
LOG_FILE="logs/paywall_flag.log"
mkdir -p logs

if [[ "${1:-}" != "on" && "${1:-}" != "off" ]]; then
    echo "Usage: $0 on|off"
    echo "  on  = PAYWALL_ENABLED=true  (web paywall live)"
    echo "  off = PAYWALL_ENABLED=false (dark, everyone premium)"
    exit 1
fi

CURRENT=$(grep "^PAYWALL_ENABLED=" "$ENV_FILE" | cut -d= -f2)
if [[ "$1" == "on" ]]; then
    NEW="true"
else
    NEW="false"
fi

if [[ "$CURRENT" == "$NEW" ]]; then
    echo "PAYWALL_ENABLED is already $NEW — no change."
    exit 0
fi

sed -i "s#^PAYWALL_ENABLED=.*#PAYWALL_ENABLED=$NEW#" "$ENV_FILE"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TIMESTAMP PAYWALL_ENABLED: $CURRENT -> $NEW" >> "$LOG_FILE"
echo "$TIMESTAMP PAYWALL_ENABLED: $CURRENT -> $NEW"
echo ""
echo "Flag changed. To take effect:"
echo "  sudo docker-compose down && sudo docker-compose up -d"
echo ""
echo "Current .env state:"
grep -E "^PAYWALL_ENABLED|^PAYWALL_TEST_FAMILY_IDS|^PAYWALL_NATIVE_ENABLED" "$ENV_FILE"
