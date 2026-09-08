#!/usr/bin/env bash
# ==============================================================================
# One-Click Let's Encrypt SSL Setup for bullsandbears.binaryunit.tech
# ==============================================================================

set -e

DOMAIN="bullsandbears.binaryunit.tech"
NGINX_CONF_AVAILABLE="/etc/nginx/sites-available/$DOMAIN"
NGINX_CONF_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"

echo "=================================================================="
echo "🔐 Setting up Let's Encrypt SSL for https://$DOMAIN"
echo "=================================================================="

# 1. Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root (or with sudo): sudo ./setup_ssl.sh"
  exit 1
fi

# 2. Install Certbot & Nginx plugin if missing
if ! command -v certbot &> /dev/null; then
    echo "📦 Installing certbot and python3-certbot-nginx..."
    apt-get update -y
    apt-get install -y certbot python3-certbot-nginx
fi

# 3. Request / Renew SSL certificate with Certbot
echo "🔑 Requesting Let's Encrypt SSL Certificate for $DOMAIN..."
certbot certonly --nginx --non-interactive --agree-tos --register-unsafely-without-email -d $DOMAIN || {
    echo "⚠️ Nginx authenticator fallback to standalone / webroot..."
    certbot certonly --webroot -w /var/www/html --non-interactive --agree-tos --register-unsafely-without-email -d $DOMAIN
}

# 4. Copy production SSL configuration
echo "📋 Applying Nginx SSL configuration..."
cp host_nginx_bullsandbears_ssl.conf $NGINX_CONF_AVAILABLE
ln -sf $NGINX_CONF_AVAILABLE $NGINX_CONF_ENABLED

# 5. Test Nginx configuration
echo "🧪 Testing Nginx configuration syntax..."
nginx -t

# 6. Reload Nginx
echo "🔄 Reloading Nginx..."
systemctl reload nginx

echo "=================================================================="
echo "✅ SSL Certificate successfully applied!"
echo "🌐 Your secure website is live at: https://$DOMAIN"
echo "=================================================================="
