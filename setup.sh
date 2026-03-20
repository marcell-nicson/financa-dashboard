#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Setup — Dashboard Financeiro Marcell
#  Execute como root no servidor Digital Ocean:
#  bash setup.sh
# ─────────────────────────────────────────────────────────────

set -e
DOMAIN="financas.promoestoque.com.br"
APP_DIR="/var/www/financa"
LOG_DIR="/var/log/financa"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Dashboard Financeiro — Setup           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. SISTEMA ─────────────────────────────────────────
echo "→ Atualizando sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# ── 2. DIRETÓRIOS ──────────────────────────────────────
echo "→ Criando diretórios..."
mkdir -p "$APP_DIR"
mkdir -p "$LOG_DIR"

# ── 3. ARQUIVOS DO APP ─────────────────────────────────
echo "→ Copiando arquivos do app..."
cp -r ./* "$APP_DIR/"
chown -R www-data:www-data "$APP_DIR"
chown -R www-data:www-data "$LOG_DIR"

# ── 4. AMBIENTE PYTHON ─────────────────────────────────
echo "→ Criando ambiente virtual Python..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
echo "→ Dependências instaladas."

# ── 5. NGINX ───────────────────────────────────────────
echo "→ Configurando Nginx..."
# Copia a config sem bloco SSL (será adicionado pelo Certbot)
cat > /etc/nginx/sites-available/financa << 'EOF'
server {
    listen 80;
    server_name financas.promoestoque.com.br;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host            $host;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60;
    }
}
EOF

ln -sf /etc/nginx/sites-available/financa /etc/nginx/sites-enabled/financa
nginx -t && systemctl reload nginx
echo "→ Nginx configurado."

# ── 6. SYSTEMD ─────────────────────────────────────────
echo "→ Configurando serviço systemd..."
cp "$APP_DIR/financa.service" /etc/systemd/system/financa.service
systemctl daemon-reload
systemctl enable financa
systemctl start financa
echo "→ Serviço iniciado."

# ── 7. CERTBOT / HTTPS ─────────────────────────────────
echo ""
echo "→ Instalando certificado HTTPS para $DOMAIN..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "marcellnicson@gmail.com" --redirect
echo "→ HTTPS ativo!"

# ── 8. STATUS ──────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ✅  Setup concluído!                   ║"
echo "╠══════════════════════════════════════════╣"
echo "║  🌐  https://$DOMAIN"
echo "║  📁  App em: $APP_DIR"
echo "║  📋  Logs:   $LOG_DIR"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Próximos passos:"
echo "  1. Abra https://$DOMAIN no navegador"
echo "  2. Vá em ⚙️ Configurar"
echo "  3. Cole o Access Token do Mercado Pago"
echo "  4. Configure seu Gmail + Senha de App"
echo "  5. Clique em 'Testar e-mail agora' para confirmar"
echo ""
echo "Comandos úteis:"
echo "  systemctl status financa    → ver status do app"
echo "  systemctl restart financa   → reiniciar"
echo "  tail -f $LOG_DIR/error.log  → ver logs"
echo ""
