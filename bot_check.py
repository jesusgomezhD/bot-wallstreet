"""BOT CHECK 1 sola vez (para Cron gratis). Lee env, revisa y sale.
Mismas vars que bot_cloud.py"""
import os, smtplib, requests
from email.mime.text import MIMEText
from datetime import datetime

def cfg(k, d=""):
    return os.environ.get(k, d)

DEST = cfg("CORREO_DESTINO"); REM = cfg("GMAIL_REMITENTE"); PWD = cfg("GMAIL_CLAVE_APP")
TICKERS = cfg("TICKERS", "AAPL,SPY,QQQ,EUR/USD"); ALERTAS = cfg("ALERTAS", "AAPL>250,EUR/USD>1.10")
FH = cfg("FINNHUB_KEY")

def pyahoo(s):
    s = s.strip().upper()
    y = s.replace("/", "") + "=X" if "/" in s else s
    if s == "EURUSD":
        y = "EURUSD=X"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])

def pfinnhub(s):
    if not FH:
        return None
    sym = "OANDA:EUR_USD" if "EUR" in s.upper() else s.strip().upper()
    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FH}", timeout=10)
    return float(r.json().get("c") or 0) or None

def obtener(s):
    for fn in (pfinnhub, pyahoo):
        try:
            p = fn(s)
            if p:
                return p
        except Exception:
            pass
    return None

def enviar(asunto, cuerpo):
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto; msg["From"] = REM; msg["To"] = DEST
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.starttls(); s.login(REM, PWD)
        s.sendmail(REM, [DEST], msg.as_string())

def parse(txt):
    out = []
    for part in (txt or "").split(","):
        part = part.strip()
        for op in (">=", "<=", ">", "<"):
            if op in part:
                sym, val = part.split(op, 1)
                try:
                    out.append((sym.strip().upper(), op, float(val.strip())))
                except ValueError:
                    pass
                break
    return out

ticks = [t.strip().upper() for t in TICKERS.split(",") if t.strip()]
reglas = parse(ALERTAS)
print(f"Check {datetime.now()} {ticks}", flush=True)
for sym in ticks:
    p = obtener(sym)
    print(f"{sym}={p}", flush=True)
    if p is None:
        continue
    for rs, op, meta in reglas:
        if rs != sym:
            continue
        ok = (p > meta if op == ">" else p < meta if op == "<"
              else p >= meta if op == ">=" else p <= meta)
        if ok:
            try:
                enviar(f"Alerta {sym} {op} {meta} (ahora {p})", f"Bot 24/7\n{sym} en {p}\n{sym}{op}{meta}\n{datetime.now()}")
                print(f"ALERTA {sym} enviada", flush=True)
            except Exception as e:
                print(f"Error correo: {e}", flush=True)
