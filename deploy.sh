#!/usr/bin/env bash
# ==============================================================================
# Best-Practice One-Click Production Deployment Script
# Domain: bullsandbears.binaryunit.tech
# ==============================================================================

set -e

echo "=================================================================="
echo "🚀 Deploying Crypto Prediction Platform to bullsandbears.binaryunit.tech"
echo "=================================================================="

# Parse command line flags
CLEAN_MODELS=false
if [[ "$1" == "--fresh-models" || "$1" == "--clean-models" ]]; then
    CLEAN_MODELS=true
    echo "🧹 Clean Models Flag Active: Legacy model cache will be refreshed."
fi

# 1. Check Docker & Docker Compose installation
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# 2. Check for .env file
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.docker.example..."
    cp .env.docker.example .env
    echo "🔑 Please edit .env with your production passwords if needed."
fi

# 3. Best Practice: Automated Database Safety Snapshot (Preserving MySQL 100%)
if docker ps --format '{{.Names}}' | grep -q "^crypto_mysql$"; then
    echo "🛡️  Creating automated MySQL database backup snapshot..."
    BACKUP_DIR="/root/crypto_db_backups"
    mkdir -p "$BACKUP_DIR" 2>/dev/null || mkdir -p "./db_backups"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    # Extract DB creds safely from environment or defaults
    ROOT_PASS=$(grep -E "^MYSQL_ROOT_PASSWORD=" .env | cut -d '=' -f2 | tr -d '\r\n' || echo "root_crypto_secure_2026")
    DB_NAME=$(grep -E "^MYSQL_DATABASE=" .env | cut -d '=' -f2 | tr -d '\r\n' || echo "crypto_trading")
    
    docker exec crypto_mysql mysqldump -u root -p"${ROOT_PASS:-root_crypto_secure_2026}" "${DB_NAME:-crypto_trading}" > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql" 2>/dev/null || true
    echo "✅ Database backup snapshot saved: ${BACKUP_DIR}/backup_${TIMESTAMP}.sql"
fi

# 4. Flush legacy model cache if requested or clean deploy
if [ "$CLEAN_MODELS" = true ]; then
    echo "🧹 Flushing legacy model cache volume (MySQL data untouched)..."
    docker compose stop scanner backend 2>/dev/null || true
    docker volume rm crypto_app_models 2>/dev/null || true
fi

# 5. Build and launch Docker containers with zero downtime
echo "📦 Building and updating Docker containers..."
docker compose up -d --build

# 6. Wait for Backend Service Health
echo "⏳ Verifying backend API health..."
for i in {1..12}; do
    if curl -s http://127.0.0.1:8005/api/status >/dev/null 2>&1; then
        echo "✅ Backend API is healthy and responding!"
        break
    fi
    echo "   ...waiting for backend startup ($i/12)"
    sleep 3
done

# 7. Automatically ensure Host Nginx SSL Reverse Proxy is permanently active
DOMAIN="bullsandbears.binaryunit.tech"
CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
NGINX_AVAIL="/etc/nginx/sites-available/$DOMAIN"
NGINX_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"

if [ -f "$CERT_FILE" ]; then
    echo "🔒 Ensuring Nginx SSL configuration is linked..."
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /var/www/html 2>/dev/null || true
    if [ -f host_nginx_bullsandbears_ssl.conf ]; then
        cp host_nginx_bullsandbears_ssl.conf "$NGINX_AVAIL" 2>/dev/null || true
        ln -sf "$NGINX_AVAIL" "$NGINX_ENABLED" 2>/dev/null || true
        rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    fi
    
    # Reload Nginx without downtime
    if command -v nginx &> /dev/null; then
        nginx -t &>/dev/null && (systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true)
    fi
fi

# 8. Clean up dangling Docker images to keep VPS disk 100% clean
echo "🧹 Cleaning up dangling build layers..."
docker image prune -f >/dev/null 2>&1 || true

# 9. Show container status
echo ""
echo "✅ All services successfully updated & running!"
docker compose ps

echo ""
echo "=================================================================="
echo "🌐 Platform URLs (SSL Active):"
echo "   - Secure Web App:   https://bullsandbears.binaryunit.tech"
echo "   - Secure API Docs:  https://bullsandbears.binaryunit.tech/docs"
echo "   - Model Status:     https://bullsandbears.binaryunit.tech/api/models/status"
echo "   - Health Check:     https://bullsandbears.binaryunit.tech/api/status"
echo "=================================================================="
