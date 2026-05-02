#!/usr/bin/env python3
"""
Relatório diário de internet — executado via cron às 7h.
Consolida speedtests e eventos do dia anterior + envia no Telegram.
"""

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
# Speedtests do dia anterior
# ---------------------------------------------------------------------------

def speedtests_dia_anterior() -> list:
    if not Path(cfg.DB_PATH).exists():
        return []
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    with sqlite3.connect(cfg.DB_PATH) as conn:
        return conn.execute(
            """SELECT ping_ms, download_mbps, upload_mbps, erro
               FROM speedtests
               WHERE timestamp >= ? AND timestamp < ?
               ORDER BY timestamp""",
            (f"{ontem} 00:00:00", f"{ontem} 23:59:60"),
        ).fetchall()


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
    agora      = datetime.now().strftime("%d/%m/%Y %H:%M")
    ontem_str  = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    testes     = speedtests_dia_anterior()
    eventos    = eventos_24h()

    linhas = [f"📊 <b>Relatório de Internet — {agora}</b>", ""]

    # Speedtest consolidado do dia anterior
    linhas.append(f"📶 <b>Speedtest {ontem_str}:</b>")
    if not testes:
        linhas += ["  sem dados registrados", ""]
    else:
        validos = [(t[0], t[1], t[2]) for t in testes if t[3] is None]
        erros   = sum(1 for t in testes if t[3] is not None)
        if not validos:
            linhas += [f"  todos os {len(testes)} testes falharam", ""]
        else:
            pings = [v[0] for v in validos if v[0] is not None]
            downs = [v[1] for v in validos if v[1] is not None]
            ups   = [v[2] for v in validos if v[2] is not None]
            linhas.append(f"  {len(validos)} testes ({len(testes) - len(validos)} falhas)" if erros else f"  {len(validos)} testes")
            if downs:
                linhas.append(f"  ↓ {min(downs):.1f} / {sum(downs)/len(downs):.1f} / {max(downs):.1f} Mbps  (mín/méd/máx)")
            if ups:
                linhas.append(f"  ↑ {min(ups):.1f} / {sum(ups)/len(ups):.1f} / {max(ups):.1f} Mbps  (mín/méd/máx)")
            if pings:
                linhas.append(f"  ⏱ {min(pings):.0f} / {sum(pings)/len(pings):.0f} / {max(pings):.0f} ms  (mín/méd/máx)")
            linhas.append("")

    # Incidentes
    if not eventos:
        linhas.append("✅ <b>Últimas 24h:</b> nenhum incidente registrado")
    else:
        total_offline   = sum(e[3] or 0 for e in eventos if e[0] == "offline")
        total_degradado = sum(e[3] or 0 for e in eventos if e[0] == "degradado")
        linhas += [
            "⚠️ <b>Incidentes nas últimas 24h:</b>",
            f"  🔴 Offline total:   {fmt_duracao(total_offline)}",
            f"  🟡 Degradado total: {fmt_duracao(total_degradado)}",
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
