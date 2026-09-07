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

# 3. Build and launch containers
echo "📦 Building and starting Docker containers..."
docker compose up -d --build

# 4. Show container status
echo ""
echo "✅ All services successfully launched!"
docker compose ps

echo ""
echo "=================================================================="
echo "🌐 Platform URLs:"
echo "   - Frontend Web App: http://bullsandbears.binaryunit.tech"
echo "   - Backend API Docs: http://bullsandbears.binaryunit.tech/docs"
echo "   - Health Check:     http://bullsandbears.binaryunit.tech/api/status"
echo ""
echo "🔐 To Enable SSL / HTTPS with Let's Encrypt:"
echo "   1. Ensure DNS A-record for bullsandbears.binaryunit.tech points to this VPS IP"
echo "   2. Run: docker compose run --rm certbot certonly --webroot --webroot-path /var/www/certbot -d bullsandbears.binaryunit.tech"
echo "   3. Copy SSL config: cp nginx/conf.d/ssl.conf.template nginx/conf.d/default.conf"
echo "   4. Reload Nginx: docker compose exec nginx nginx -s reload"
echo "=================================================================="
