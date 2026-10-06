"""BOT NUBE 24/7 - Sin ventana. Lee config de variables de entorno Render.
En manos de Dios. En el nombre de Jesucristo. Amen."""
import os, time, smtplib, requests
from email.mime.text import MIMEText
from datetime import datetime

def cfg(k, default=""):
    return os.environ.get(k, default)

CORREO_DESTINO = cfg("CORREO_DESTINO")
GMAIL_REMITENTE = cfg("GMAIL_REMITENTE")
GMAIL_CLAVE_APP = cfg("GMAIL_CLAVE_APP")
TICKERS = cfg("TICKERS", "AAPL,SPY,QQQ,EUR/USD")
ALERTAS = cfg("ALERTAS", "AAPL>250,EUR/USD>1.10")
FINNHUB_KEY = cfg("FINNHUB_KEY")
ALPACA_KEY = cfg("ALPACA_KEY")
ALPACA_SECRET = cfg("ALPACA_SECRET")
INTERVALO = int(cfg("INTERVALO_SEG", "60"))

def precio_yahoo(s):
    s = s.strip().upper()
    y = s.replace("/", "") + "=X" if "/" in s else s
    if s == "EURUSD":
        y = "EURUSD=X"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    r.raise_for_status()
    return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])

def precio_finnhub(s):
    if not FINNHUB_KEY:
        return None
    sym = "OANDA:EUR_USD" if "EUR" in s.upper() else s.strip().upper()
    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}", timeout=10)
    return float(r.json().get("c") or 0) or None

def precio_alpaca(s):
    if not ALPACA_KEY or "/" in s:
        return None
    r = requests.get(f"https://data.alpaca.markets/v2/stocks/{s.strip().upper()}/trades/latest",
        headers={"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}, timeout=10)
    if r.status_code != 200:
        return None
    return float(r.json()["trade"]["p"])

def obtener(s):
    for fn, nombre in [(precio_alpaca, "Alpaca"), (precio_finnhub, "Finnhub"), (precio_yahoo, "Yahoo")]:
        try:
            p = fn(s)
            if p:
                return p, nombre
        except Exception:
            pass
    return None, "-"

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

def enviar(asunto, cuerpo):
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = GMAIL_REMITENTE
    msg["To"] = CORREO_DESTINO
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.starttls()
        s.login(GMAIL_REMITENTE, GMAIL_CLAVE_APP)
        s.sendmail(GMAIL_REMITENTE, [CORREO_DESTINO], msg.as_string())

def main():
    print(f"Bot nube iniciado {datetime.now()} | Tickers: {TICKERS}", flush=True)
    if not CORREO_DESTINO or not GMAIL_REMITENTE or not GMAIL_CLAVE_APP:
        print("FALTAN variables CORREO_DESTINO / GMAIL_REMITENTE / GMAIL_CLAVE_APP", flush=True)
        return
    reglas = parse(ALERTAS)
    avisados = set()
    tickers = [t.strip().upper() for t in TICKERS.split(",") if t.strip()]
    while True:
        for sym in tickers:
            p, fuente = obtener(sym)
            print(f"{datetime.now():%H:%M:%S} {sym}={p} ({fuente})", flush=True)
            if p is None:
                continue
            for rs, op, meta in reglas:
                if rs != sym:
                    continue
                ok = (p > meta if op == ">" else p < meta if op == "<"
                      else p >= meta if op == ">=" else p <= meta)
                if ok and f"{sym}{op}{meta}" not in avisados:
                    avisados.add(f"{sym}{op}{meta}")
                    try:
                        enviar(f"Alerta {sym} {op} {meta} (ahora {p})",
                              f"Bot Wall Street\n\n{sym} en {p}\nCondicion {sym}{op}{meta}\nFuente {fuente}\n{datetime.now()}")
                        print(f"ALERTA enviada {sym}", flush=True)
                    except Exception as e:
                        print(f"Error correo: {e}", flush=True)
        time.sleep(INTERVALO)

if __name__ == "__main__":
    main()
