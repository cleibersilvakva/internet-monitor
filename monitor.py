#!/usr/bin/env python3
"""
Daemon de monitoramento de internet — Raspberry Pi
Detecta quedas/degradação, registra eventos em SQLite, notifica via Telegram.
"""

import time
import subprocess
import sqlite3
import urllib.request
import urllib.parse
import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import config as cfg

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(cfg.LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

def init_db():
    Path(cfg.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cfg.DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo        TEXT NOT NULL,
                inicio      TEXT NOT NULL,
                fim         TEXT,
                duracao_seg INTEGER,
                latencia_ms REAL,
                perda_pct   REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS speedtests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT NOT NULL,
                ping_ms       REAL,
                download_mbps REAL,
                upload_mbps   REAL,
                erro          TEXT
            )
        """)


def db_iniciar_evento(tipo: str, latencia: float, perda: float) -> int:
    with sqlite3.connect(cfg.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO eventos (tipo, inicio, latencia_ms, perda_pct) VALUES (?,?,?,?)",
            (tipo, datetime.now().isoformat(), latencia, perda),
        )
        return cur.lastrowid


def db_salvar_speedtest(ping_ms, download_mbps, upload_mbps, erro=None):
    with sqlite3.connect(cfg.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO speedtests (timestamp, ping_ms, download_mbps, upload_mbps, erro) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), ping_ms, download_mbps, upload_mbps, erro),
        )


def db_encerrar_evento(event_id: int) -> int:
    """Preenche fim e duracao. Retorna duração em segundos."""
    with sqlite3.connect(cfg.DB_PATH) as conn:
        row = conn.execute(
            "SELECT inicio FROM eventos WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return 0
        duracao = int((datetime.now() - datetime.fromisoformat(row[0])).total_seconds())
        conn.execute(
            "UPDATE eventos SET fim = ?, duracao_seg = ? WHERE id = ?",
            (datetime.now().isoformat(), duracao, event_id),
        )
        return duracao


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def telegram(msg: str) -> bool:
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(url, data=data), timeout=10
        )
        return True
    except Exception as e:
        log.warning(f"Telegram falhou: {e}")
        return False


# ---------------------------------------------------------------------------
# Speedtest periódico
# ---------------------------------------------------------------------------

def _run_speedtest():
    log.info("Speedtest iniciado")
    try:
        res = subprocess.run(
            ["speedtest-cli", "--simple"],
            capture_output=True, text=True, timeout=cfg.SPEEDTEST_TIMEOUT_S,
        )
        ping_ms = download_mbps = upload_mbps = None
        for linha in res.stdout.strip().splitlines():
            m = re.search(r"[\d.]+", linha)
            if not m:
                continue
            val = float(m.group())
            if   "Ping"     in linha: ping_ms       = val
            elif "Download" in linha: download_mbps = val
            elif "Upload"   in linha: upload_mbps   = val
        if download_mbps is None:
            erro = res.stderr.strip() or "sem saída"
            db_salvar_speedtest(None, None, None, erro)
            log.warning(f"Speedtest falhou: {erro}")
        else:
            db_salvar_speedtest(ping_ms, download_mbps, upload_mbps)
            log.info(f"Speedtest: ↓{download_mbps}Mbps ↑{upload_mbps}Mbps ping={ping_ms}ms")
    except subprocess.TimeoutExpired:
        db_salvar_speedtest(None, None, None, "timeout")
        log.warning("Speedtest timeout")
    except FileNotFoundError:
        db_salvar_speedtest(None, None, None, "speedtest-cli não encontrado")
        log.warning("speedtest-cli não encontrado")
    except Exception as e:
        db_salvar_speedtest(None, None, None, str(e))
        log.warning(f"Speedtest erro: {e}")


def _speedtest_loop():
    while True:
        _run_speedtest()
        time.sleep(cfg.SPEEDTEST_INTERVAL_S)


# ---------------------------------------------------------------------------
# Ping / checagem de conectividade
# ---------------------------------------------------------------------------

def ping(host: str) -> tuple[float, float]:
    """Retorna (latencia_ms, perda_pct). Em falha total: (-1, 100)."""
    try:
        res = subprocess.run(
            ["ping", "-c", str(cfg.PING_COUNT), "-W", str(cfg.PING_TIMEOUT_S), host],
            capture_output=True, text=True,
            timeout=cfg.PING_COUNT * (cfg.PING_TIMEOUT_S + 1) + 2,
        )
        latencia = -1.0
        perda = 100.0
        for linha in res.stdout.splitlines():
            if "packet loss" in linha:
                perda = float(linha.split("%")[0].split()[-1])
            if linha.startswith("rtt") or "round-trip" in linha:
                latencia = float(linha.split("=")[1].strip().split("/")[1])
        return latencia, perda
    except Exception:
        return -1.0, 100.0


def checar_conexao() -> dict:
    """
    Retorna {status, latencia_ms, perda_pct}.
    status: 'online' | 'degradado' | 'offline'
    """
    resultados = [ping(h) for h in cfg.PING_HOSTS]
    latencias  = [l for l, _ in resultados if l > 0]
    perdas     = [p for _, p in resultados]

    avg_perda   = sum(perdas) / len(perdas)
    avg_lat     = sum(latencias) / len(latencias) if latencias else -1.0

    if avg_perda >= 90:
        return {"status": "offline",   "latencia_ms": -1,      "perda_pct": avg_perda}
    if avg_perda >= cfg.PACKET_LOSS_WARN or avg_lat >= cfg.LATENCY_WARN_MS:
        return {"status": "degradado", "latencia_ms": avg_lat,  "perda_pct": avg_perda}
    return     {"status": "online",    "latencia_ms": avg_lat,  "perda_pct": avg_perda}


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def fmt_duracao(segundos: int) -> str:
    if segundos < 60:
        return f"{segundos}s"
    if segundos < 3600:
        return f"{segundos // 60}min {segundos % 60}s"
    h, r = divmod(segundos, 3600)
    return f"{h}h {r // 60}min"


def fmt_agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def run():
    init_db()
    log.info("Monitor iniciado")
    telegram("🟢 <b>Monitor de Internet iniciado</b>\nRaspberry Pi monitorando sua conexão a cada 30s.")

    t = threading.Thread(target=_speedtest_loop, daemon=True)
    t.start()

    estado        = "online"
    evento_id     = None          # ID do evento aberto no DB
    offline_inicio = None         # Hora de início do offline (para msg de retorno)
    msg_offline_pendente = None   # Guarda msg offline se Telegram falhou durante queda

    while True:
        check     = checar_conexao()
        novo_estado = check["status"]

        if novo_estado != estado:
            agora = fmt_agora()

            # --- ficou offline ---
            if novo_estado == "offline":
                if evento_id:               # era degradado — encerra esse evento
                    db_encerrar_evento(evento_id)
                evento_id      = db_iniciar_evento("offline", check["latencia_ms"], check["perda_pct"])
                offline_inicio = datetime.now()
                msg = (
                    f"🔴 <b>Internet CAIU</b>\n"
                    f"🕐 {agora}\n"
                    f"📡 Perda de pacotes: {check['perda_pct']:.0f}%"
                )
                if not telegram(msg):
                    msg_offline_pendente = msg   # guarda para reenviar quando voltar

            # --- ficou degradado (saiu de online) ---
            elif novo_estado == "degradado" and estado == "online":
                evento_id = db_iniciar_evento("degradado", check["latencia_ms"], check["perda_pct"])
                telegram(
                    f"🟡 <b>Internet DEGRADADA</b>\n"
                    f"🕐 {agora}\n"
                    f"⏱ Latência: {check['latencia_ms']:.0f}ms\n"
                    f"📡 Perda: {check['perda_pct']:.0f}%"
                )

            # --- voltou ao normal ---
            elif novo_estado == "online":
                duracao = 0
                if evento_id:
                    duracao = db_encerrar_evento(evento_id)
                    evento_id = None

                tipo_anterior = "offline" if estado == "offline" else "degradada"
                emoji_anterior = "🔴" if estado == "offline" else "🟡"

                if msg_offline_pendente:
                    # Reenviar mensagem de queda que não foi entregue
                    telegram(msg_offline_pendente + "\n<i>(mensagem atrasada — Pi estava sem internet)</i>")
                    msg_offline_pendente = None

                telegram(
                    f"🟢 <b>Internet voltou!</b>\n"
                    f"🕐 {agora}\n"
                    f"{emoji_anterior} Ficou {tipo_anterior}: <b>{fmt_duracao(duracao)}</b>\n"
                    f"⏱ Latência atual: {check['latencia_ms']:.0f}ms"
                )
                offline_inicio = None

            log.info(f"Estado: {estado} → {novo_estado} | lat={check['latencia_ms']:.0f}ms perda={check['perda_pct']:.0f}%")
            estado = novo_estado

        time.sleep(cfg.CHECK_INTERVAL_S)


if __name__ == "__main__":
    run()
