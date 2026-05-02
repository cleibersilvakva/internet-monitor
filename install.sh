#!/bin/bash
# Executar no Raspberry Pi: bash install.sh
set -e

INSTALL_DIR="/opt/internet-monitor"
SERVICE="internet-monitor"
CURRENT_USER="$(whoami)"

echo "=== Instalando dependências ==="
sudo apt-get update -q
sudo apt-get install -y python3 speedtest-cli

echo "=== Criando diretórios ==="
sudo mkdir -p "$INSTALL_DIR/data"
sudo chown -R "$CURRENT_USER:$CURRENT_USER" "$INSTALL_DIR"

echo "=== Copiando arquivos ==="
cp config.py monitor.py report.py "$INSTALL_DIR/"

echo "=== Configurando log ==="
sudo touch /var/log/internet-monitor.log
sudo chown "$CURRENT_USER:$CURRENT_USER" /var/log/internet-monitor.log

echo "=== Instalando serviço systemd ==="
# Gera o service com o usuário correto
sed "s/User=pi/User=$CURRENT_USER/" internet-monitor.service > /tmp/internet-monitor.service
sudo cp /tmp/internet-monitor.service /etc/systemd/system/internet-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl start  "$SERVICE"

echo "=== Configurando cron (relatório diário às 7h) ==="
CRON_JOB="0 7 * * * /usr/bin/python3 /opt/internet-monitor/report.py >> /var/log/internet-monitor.log 2>&1"
( crontab -l 2>/dev/null | grep -v "report.py"; echo "$CRON_JOB" ) | crontab -

echo ""
echo "======================================================"
echo "  Instalado! Próximos passos:"
echo "  1. Edite o token e chat_id:"
echo "     nano /opt/internet-monitor/config.py"
echo "  2. Reinicie o serviço:"
echo "     sudo systemctl restart internet-monitor"
echo "  3. Teste o relatório agora:"
echo "     python3 /opt/internet-monitor/report.py"
echo "  4. Acompanhe o log:"
echo "     journalctl -u internet-monitor -f"
echo "======================================================"
