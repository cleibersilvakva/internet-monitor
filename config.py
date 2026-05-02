# Telegram
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_AQUI"
TELEGRAM_CHAT_ID   = "SEU_CHAT_ID_AQUI"

# Hosts testados em paralelo — 2/3 falhando = degradado, todos = offline
PING_HOSTS  = ["8.8.8.8", "1.1.1.1", "1.0.0.1"]
PING_COUNT  = 3           # pings por host
PING_TIMEOUT_S = 2        # timeout por ping

# Intervalo entre rodadas de checagem
CHECK_INTERVAL_S = 30

# Limites para classificar como "degradado"
LATENCY_WARN_MS   = 200   # ms
PACKET_LOSS_WARN  = 30    # %

# Speedtest periódico (a cada 30 min) e timeout por execução
SPEEDTEST_INTERVAL_S = 1800
SPEEDTEST_TIMEOUT_S  = 90

# Arquivo de log de eventos (SQLite)
DB_PATH = "/opt/internet-monitor/data/events.db"

# Arquivo de log de texto
LOG_PATH = "/var/log/internet-monitor.log"
