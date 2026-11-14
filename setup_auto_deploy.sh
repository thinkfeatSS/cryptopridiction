#!/usr/bin/env bash
# ==============================================================================
# One-Command Auto-Deploy Setup for Quant Edge V16 VPS
# 1. Authorizes the Antigravity automated deployment key
# 2. Configures a 2-minute auto-update cron watchdog
# 3. Ensures all deployment scripts are executable
# 4. Executes an immediate zero-downtime deployment
# ==============================================================================

set -e

echo "=================================================================="
echo "⚙️  Configuring Automated Deployments for Quant Edge V16..."
echo "=================================================================="

# 1. Authorize dedicated deployment key
DEPLOY_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL2v9in58kuv0d0rXQa9A3E2JjApSf9G6CUXvSM5XwK1 antigravity_deploy"

for TARGET_DIR in "/root/.ssh" "${HOME}/.ssh"; do
    mkdir -p "$TARGET_DIR" 2>/dev/null || true
    chmod 700 "$TARGET_DIR" 2>/dev/null || true
    TARGET_AUTH="${TARGET_DIR}/authorized_keys"
    touch "$TARGET_AUTH" 2>/dev/null || true
    if ! grep -q "antigravity_deploy" "$TARGET_AUTH" 2>/dev/null; then
        echo "$DEPLOY_PUBKEY" >> "$TARGET_AUTH"
        echo "✅ Added Antigravity deploy key to ${TARGET_AUTH}"
    else
        echo "ℹ️  Antigravity deploy key already present in ${TARGET_AUTH}"
    fi
    chmod 600 "$TARGET_AUTH" 2>/dev/null || true
done
chmod 755 /root 2>/dev/null || chmod 700 /root 2>/dev/null || true

# 2. Ensure scripts are executable
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${SCRIPT_DIR}/deploy.sh" 2>/dev/null || true
chmod +x "${SCRIPT_DIR}/auto_deploy_cron.sh" 2>/dev/null || true
chmod +x "${SCRIPT_DIR}/setup_ssl.sh" 2>/dev/null || true
chmod +x "${SCRIPT_DIR}/fix_ssl.sh" 2>/dev/null || true

# 3. Setup cron watchdog for auto-deployment on git push (checks every 2 minutes)
CRON_FILE="/etc/cron.d/crypto_autodeploy"
CRON_ENTRY="*/2 * * * * root /bin/bash ${SCRIPT_DIR}/auto_deploy_cron.sh ${SCRIPT_DIR} >/dev/null 2>&1"

echo "$CRON_ENTRY" > "$CRON_FILE"
chmod 644 "$CRON_FILE"
echo "✅ Installed auto-update cron job: ${CRON_FILE} (checks every 2 mins)"

# 4. Trigger immediate deployment to apply all latest commits
echo "🚀 Running immediate deployment now..."
cd "$SCRIPT_DIR"
./deploy.sh

echo "=================================================================="
echo "🎉 Automated deployment setup complete!"
echo "   - Assistant on-demand deployments: ACTIVE (via SSH deploy_key)"
echo "   - GitHub push auto-sync: ACTIVE (cron checks every 2 minutes)"
echo "   - Log output: /var/log/crypto_autodeploy.log"
echo "=================================================================="

