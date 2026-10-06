"""BOT CHECK 1 sola vez (para Cron gratis). Lee env, revisa y sale.
Mismas vars que bot_cloud.py"""
import os, smtplib, requests
from email.mime.text import MIMEText
from datetime import datetime

def cfg(k, d=""):
    return os.environ.get(k, d)

DEST = cfg("CORREO_DESTINO"); REM = cfg("GMAIL_REMITENTE"); PWD = cfg("GMAIL_CLAVE_APP")
# Prioridad: lo que escribes en el formulario (Run workflow) > secretos fijos
TICKERS = cfg("INPUT_TICKERS") or cfg("TICKERS", "AAPL,SPY,QQQ,EUR/USD")
ALERTAS = cfg("INPUT_ALERTAS") or cfg("ALERTAS", "")
FH = cfg("FINNHUB_KEY")
try:
    UMBRAL_PCT = float(cfg("INPUT_UMBRAL") or cfg("UMBRAL_PCT", "2"))
except ValueError:
    UMBRAL_PCT = 2.0

def pyahoo(s):
    """Devuelve (precio, cierre_anterior). Gratis sin clave."""
    s = s.strip().upper()
    y = s.replace("/", "") + "=X" if "/" in s else s
    if s == "EURUSD":
        y = "EURUSD=X"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    meta = r.json()["chart"]["result"][0]["meta"]
    return float(meta["regularMarketPrice"]), float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0) or None

def pfinnhub(s):
    if not FH:
        return None
    sym = "OANDA:EUR_USD" if "EUR" in s.upper() else s.strip().upper()
    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FH}", timeout=10)
    return float(r.json().get("c") or 0) or None

def obtener(s):
    for fn in (pfinnhub, pyahoo):
        try:
            r = fn(s)
            if r:
                # pfinnhub devuelve precio; pyahoo devuelve (precio, previo)
                if isinstance(r, tuple):
                    return r[0], r[1]
                return r, None
        except Exception:
            pass
    return None, None

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
print(f"Check {datetime.now()} | {len(ticks)} tickers | umbral {UMBRAL_PCT}%", flush=True)
for sym in ticks:
    p, previo = obtener(sym)
    if p is None:
        print(f"{sym}=sin dato", flush=True)
        continue
    pct = round((p - previo) / previo * 100, 2) if previo else 0.0
    marca = " 🔔" if abs(pct) >= UMBRAL_PCT else ""
    print(f"{sym}={p} ({pct}%){marca}", flush=True)
    # 1) Alerta automatica por % (sin poner precios): vale para los 80
    if abs(pct) >= UMBRAL_PCT:
        try:
            enviar(f"{'🚀' if pct > 0 else '🔻'} {sym} {pct:+}% (ahora {p})",
                  f"Bot 24/7\n{sym} en {p}\nCambio del dia: {pct:+}%\nUmbral: {UMBRAL_PCT}%\n{datetime.now()}")
            print(f"ALERTA % {sym} enviada", flush=True)
        except Exception as e:
            print(f"Error correo: {e}", flush=True)
    # 2) Reglas de precio clasicas (opcional)
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
