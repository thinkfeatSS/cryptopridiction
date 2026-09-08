#!/usr/bin/env bash
# ==============================================================================
# Bulletproof SSL Provisioner for bullsandbears.binaryunit.tech
# Resolves port 80 conflicts automatically (Standalone Mode)
# ==============================================================================

set -e

DOMAIN="bullsandbears.binaryunit.tech"

echo "=================================================================="
echo "🔐 Starting Bulletproof SSL Provisioner for https://$DOMAIN"
echo "=================================================================="

# 1. Verify root permissions
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root: sudo ./fix_ssl.sh"
  exit 1
fi

# 2. Install certbot if missing
if ! command -v certbot &> /dev/null; then
    echo "📦 Installing certbot..."
    apt-get update -y
    apt-get install -y certbot
fi

# 3. Temporarily disable host nginx broken site symlink to prevent syntax block
rm -f /etc/nginx/sites-enabled/$DOMAIN || true

# 4. Identify containers or processes listening on port 80
echo "🔍 Freeing Port 80 for SSL verification..."
CONTAINERS_PORT_80=$(docker ps -q --filter "publish=80" 2>/dev/null || true)
if [ -n "$CONTAINERS_PORT_80" ]; then
    echo "⏸️  Temporarily pausing Docker container(s) on port 80: $CONTAINERS_PORT_80"
    docker stop $CONTAINERS_PORT_80
fi

# Also stop host nginx if it was running
systemctl stop nginx 2>/dev/null || true

# 5. Issue Let's Encrypt Certificate via Standalone Authenticator
echo "🔑 Requesting official Let's Encrypt SSL certificate for $DOMAIN..."
certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --force-renewal

# 6. Verify certificate files exist
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "✅ SSL Certificate successfully issued at /etc/letsencrypt/live/$DOMAIN/"
else
    echo "❌ Certificate file not found. Check /var/log/letsencrypt/letsencrypt.log"
    # Restart containers before exit
    if [ -n "$CONTAINERS_PORT_80" ]; then
        docker start $CONTAINERS_PORT_80 || true
    fi
    exit 1
fi

# 7. Restart Docker containers on port 80
if [ -n "$CONTAINERS_PORT_80" ]; then
    echo "▶️  Restarting Docker containers: $CONTAINERS_PORT_80"
    docker start $CONTAINERS_PORT_80
    sleep 2
    
    # Reload Docker Nginx if present
    for cid in $CONTAINERS_PORT_80; do
        docker exec $cid nginx -s reload 2>/dev/null || true
    done
fi

# 8. Configure host Nginx if host Nginx is being used
if [ -d "/etc/nginx/sites-available" ]; then
    echo "📋 Applying host Nginx SSL configuration..."
    cp host_nginx_bullsandbears_ssl.conf /etc/nginx/sites-available/$DOMAIN
    ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
    
    # Test and start/reload host nginx if no port conflict
    if nginx -t 2>/dev/null; then
        systemctl start nginx 2>/dev/null || systemctl reload nginx 2>/dev/null || true
    fi
fi

echo ""
echo "=================================================================="
echo "🎉 SSL Certificate Successfully Installed & Active!"
echo "🌐 Visit your secure HTTPS site: https://$DOMAIN"
echo "=================================================================="
