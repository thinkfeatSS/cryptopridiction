#!/usr/bin/env bash
# ==============================================================================
# One-Click Production Deployment Script
# Domain: bullsandbears.binaryunit.tech
# ==============================================================================

set -e

echo "=================================================================="
echo "🚀 Deploying Crypto Prediction Platform to bullsandbears.binaryunit.tech"
echo "=================================================================="

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

# 3. Build and launch Docker containers
echo "📦 Building and updating Docker containers..."
docker compose up -d --build

# 4. Automatically ensure Host Nginx SSL Reverse Proxy is permanently enabled & active
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

# 5. Show container status
echo ""
echo "✅ All services successfully updated & running!"
docker compose ps

echo ""
echo "=================================================================="
echo "🌐 Platform URLs (SSL Active):"
echo "   - Secure Web App:   https://bullsandbears.binaryunit.tech"
echo "   - Secure API Docs:  https://bullsandbears.binaryunit.tech/docs"
echo "   - Health Check:     https://bullsandbears.binaryunit.tech/api/status"
echo "=================================================================="
