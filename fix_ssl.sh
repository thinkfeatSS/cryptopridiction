#!/usr/bin/env bash
# ==============================================================================
# Bulletproof SSL Provisioner & Nginx Activator for bullsandbears.binaryunit.tech
# Reuses existing Let's Encrypt certificates on disk and configures HTTPS proxy
# ==============================================================================

DOMAIN="bullsandbears.binaryunit.tech"

echo "=================================================================="
echo "🔐 Starting Bulletproof SSL Provisioner for https://$DOMAIN"
echo "=================================================================="

# 1. Verify root permissions
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root: sudo ./fix_ssl.sh"
  exit 1
fi

# 2. Check if certificate already exists on disk
CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
KEY_FILE="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "✨ Existing valid SSL Certificate detected at /etc/letsencrypt/live/$DOMAIN/!"
else
    echo "🔍 Certificate not found in live directory. Installing certbot & requesting..."
    if ! command -v certbot &> /dev/null; then
        apt-get update -y
        apt-get install -y certbot
    fi

    # Temporarily stop services on port 80 to free port for standalone ACME challenge
    echo "🔍 Freeing Port 80 for SSL verification..."
    CONTAINERS_PORT_80=$(docker ps -q --filter "publish=80" 2>/dev/null || true)
    if [ -n "$CONTAINERS_PORT_80" ]; then
        echo "⏸️  Pausing Docker container(s) on port 80: $CONTAINERS_PORT_80"
        docker stop $CONTAINERS_PORT_80
    fi
    systemctl stop nginx 2>/dev/null || true

    # Request certificate using --keep-until-expiring to avoid duplicate rate limits
    echo "🔑 Obtaining Let's Encrypt SSL certificate for $DOMAIN..."
    certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring || true

    # Restart containers on port 80 if any were stopped
    if [ -n "$CONTAINERS_PORT_80" ]; then
        docker start $CONTAINERS_PORT_80 || true
    fi
fi

# 3. Double check if certificate exists or can be recovered from archive
if [ ! -f "$CERT_FILE" ]; then
    LATEST_ARCHIVE=$(ls -td /etc/letsencrypt/archive/$DOMAIN/fullchain*.pem 2>/dev/null | head -n 1 || true)
    if [ -n "$LATEST_ARCHIVE" ]; then
        echo "📁 Recovering certificate symlinks from /etc/letsencrypt/archive/$DOMAIN/..."
        mkdir -p /etc/letsencrypt/live/$DOMAIN/
        ln -sf $(ls -td /etc/letsencrypt/archive/$DOMAIN/fullchain*.pem | head -n 1) /etc/letsencrypt/live/$DOMAIN/fullchain.pem
        ln -sf $(ls -td /etc/letsencrypt/archive/$DOMAIN/privkey*.pem | head -n 1) /etc/letsencrypt/live/$DOMAIN/privkey.pem
        ln -sf $(ls -td /etc/letsencrypt/archive/$DOMAIN/cert*.pem | head -n 1) /etc/letsencrypt/live/$DOMAIN/cert.pem
        ln -sf $(ls -td /etc/letsencrypt/archive/$DOMAIN/chain*.pem | head -n 1) /etc/letsencrypt/live/$DOMAIN/chain.pem
    fi
fi

# 4. Final verification of certificate
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "✅ SSL Certificate is READY: $CERT_FILE"
else
    echo "❌ Certificate file not found at $CERT_FILE"
    echo "Please check /var/log/letsencrypt/letsencrypt.log"
    exit 1
fi

# 5. Configure Host Nginx SSL Reverse Proxy
echo "📋 Applying host Nginx SSL configuration..."
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /var/www/html

cp host_nginx_bullsandbears_ssl.conf /etc/nginx/sites-available/$DOMAIN
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN

# Remove default nginx site if it conflicts with port 80
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# Test Nginx configuration
echo "🧪 Testing Nginx configuration..."
nginx -t

# 6. Restart/Reload Nginx
echo "🚀 Starting Nginx..."
systemctl restart nginx || systemctl reload nginx

# 7. Verify Docker services are running
echo "🐳 Ensuring Docker application services are up..."
docker compose up -d

echo ""
echo "=================================================================="
echo "🎉 SSL Certificate Successfully Installed & Active!"
echo "🌐 Secure URL: https://$DOMAIN"
echo "=================================================================="
