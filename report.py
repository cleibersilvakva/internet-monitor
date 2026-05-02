#!/usr/bin/env python3
"""
Relatório diário de internet — executado via cron às 7h.
Faz speedtest + consolida eventos das últimas 24h + envia no Telegram.
"""

import subprocess
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import config as cfg


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def telegram(msg: str):
    url  = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
    }).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)


# ---------------------------------------------------------------------------
# Speedtest
# ---------------------------------------------------------------------------

def speedtest() -> dict:
    try:
        res = subprocess.run(
            ["python3", "-m", "speedtest", "--simple"],
            capture_output=True, text=True, timeout=cfg.SPEEDTEST_TIMEOUT_S,
        )
        data = {}
        for linha in res.stdout.strip().splitlines():
            if "Ping"     in linha: data["ping"]     = linha.split(":", 1)[1].strip()
            if "Download" in linha: data["download"] = linha.split(":", 1)[1].strip()
            if "Upload"   in linha: data["upload"]   = linha.split(":", 1)[1].strip()
        return data if data else {"erro": res.stderr.strip() or "sem saída"}
    except subprocess.TimeoutExpired:
        return {"erro": "timeout"}
    except FileNotFoundError:
        return {"erro": "speedtest-cli não encontrado"}
    except Exception as e:
        return {"erro": str(e)}


# ---------------------------------------------------------------------------
# Eventos das últimas 24h
# ---------------------------------------------------------------------------

def eventos_24h() -> list:
    if not Path(cfg.DB_PATH).exists():
        return []
    desde = (datetime.now() - timedelta(hours=24)).isoformat()
    with sqlite3.connect(cfg.DB_PATH) as conn:
        return conn.execute(
            "SELECT tipo, inicio, fim, duracao_seg FROM eventos WHERE inicio >= ? ORDER BY inicio",
            (desde,),
        ).fetchall()


def fmt_duracao(seg) -> str:
    if seg is None:
        return "em andamento"
    if seg < 60:
        return f"{seg}s"
    if seg < 3600:
        return f"{seg // 60}min {seg % 60}s"
    h, r = divmod(seg, 3600)
    return f"{h}h {r // 60}min"


def fmt_hora(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M")


# ---------------------------------------------------------------------------
# Montar e enviar relatório
# ---------------------------------------------------------------------------

def gerar_relatorio() -> str:
    agora    = datetime.now().strftime("%d/%m/%Y %H:%M")
    speed    = speedtest()
    eventos  = eventos_24h()

    linhas = [f"📊 <b>Relatório de Internet — {agora}</b>", ""]

    # Velocidade
    if "erro" not in speed:
        linhas += [
            "📶 <b>Velocidade atual:</b>",
            f"  ↓ {speed.get('download', '?')}",
            f"  ↑ {speed.get('upload',   '?')}",
            f"  ⏱ {speed.get('ping',     '?')}",
            "",
        ]
    else:
        linhas += [f"📶 Speedtest indisponível: {speed['erro']}", ""]

    # Incidentes
    if not eventos:
        linhas.append("✅ <b>Últimas 24h:</b> nenhum incidente registrado")
    else:
        total_offline  = sum(e[3] or 0 for e in eventos if e[0] == "offline")
        total_degradado = sum(e[3] or 0 for e in eventos if e[0] == "degradado")
        linhas += [
            f"⚠️ <b>Incidentes nas últimas 24h:</b>",
            f"  🔴 Offline total:    {fmt_duracao(total_offline)}",
            f"  🟡 Degradado total:  {fmt_duracao(total_degradado)}",
            "",
        ]
        for tipo, inicio, fim, duracao in eventos:
            emoji   = "🔴" if tipo == "offline" else "🟡"
            fim_str = fmt_hora(fim) if fim else "em andamento"
            linhas.append(f"  {emoji} {fmt_hora(inicio)} → {fim_str}  ({fmt_duracao(duracao)})")

    return "\n".join(linhas)


if __name__ == "__main__":
    relatorio = gerar_relatorio()
    telegram(relatorio)
    print(relatorio)
