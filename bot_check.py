"""BOT CHECK 1 sola vez (para Cron gratis). Lee env, revisa y sale.
Mismas vars que bot_cloud.py"""
import os, smtplib, requests
from email.mime.text import MIMEText
from datetime import datetime

def cfg(k, d=""):
    return os.environ.get(k, d)

# Pausa de emergencia: si existe archivo PAUSADO en el repo, no envia nada
_BASE = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(_BASE, "PAUSADO")):
    print("Bot pausado por el usuario. Sin envios.", flush=True)
    raise SystemExit(0)

DEST = cfg("CORREO_DESTINO"); REM = cfg("GMAIL_REMITENTE"); PWD = cfg("GMAIL_CLAVE_APP")
# Prioridad: formulario Run workflow > archivo config_nube.json (app PC) > secretos
import json as _json
_arch = {}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_nube.json"), encoding="utf-8") as _f:
        _arch = _json.load(_f)
except Exception:
    pass
TICKERS = cfg("INPUT_TICKERS") or _arch.get("tickers") or cfg("TICKERS", "AAPL,SPY,QQQ,EUR/USD")
ALERTAS = cfg("INPUT_ALERTAS") or _arch.get("alertas") or cfg("ALERTAS", "")
FH = cfg("FINNHUB_KEY")
try:
    UMBRAL_PCT = float(cfg("INPUT_UMBRAL") or str(_arch.get("umbral_pct", "")) or cfg("UMBRAL_PCT", "2"))
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

# Estado para avisar 1 sola vez (no spam cada 5 min). En la nube se guarda en el repo.
ESTADO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")
try:
    with open(ESTADO_FILE, encoding="utf-8") as _f:
        ESTADO = _json.load(_f)
except Exception:
    ESTADO = {}
hoy = datetime.now().strftime("%Y-%m-%d")
if ESTADO.get("fecha") != hoy:
    ESTADO = {"fecha": hoy, "pct": [], "precios": {}}

def ya_avisado(clave, grupo):
    return clave in ESTADO.get(grupo, [] if grupo == "pct" else {})

def marcar(clave, grupo, activo=True):
    if grupo == "pct":
        if clave not in ESTADO["pct"]:
            ESTADO["pct"].append(clave)
    else:
        ESTADO["precios"][clave] = activo

ticks = [t.strip().upper() for t in TICKERS.split(",") if t.strip()]
reglas = parse(ALERTAS)
print(f"Check {datetime.now()} | {len(ticks)} tickers | umbral {UMBRAL_PCT}%", flush=True)
cambios = False
for sym in ticks:
    p, previo = obtener(sym)
    if p is None:
        print(f"{sym}=sin dato", flush=True)
        continue
    pct = round((p - previo) / previo * 100, 2) if previo else 0.0
    marca = " [ALERTA]" if abs(pct) >= UMBRAL_PCT else ""
    print(f"{sym}={p} ({pct}%){marca}", flush=True)
    # 1) Alerta automatica por % (1 vez al dia por ticker)
    if abs(pct) >= UMBRAL_PCT and not ya_avisado(sym, "pct"):
        try:
            enviar(f"{'SUBE' if pct > 0 else 'BAJA'} {sym} {pct:+}% (ahora {p})",
                  f"Bot 24/7\n{sym} en {p}\nCambio del dia: {pct:+}%\nUmbral: {UMBRAL_PCT}%\n{datetime.now()}")
            print(f"ALERTA % {sym} enviada", flush=True)
            marcar(sym, "pct"); cambios = True
        except Exception as e:
            print(f"Error correo: {e}", flush=True)
    # 2) Reglas de precio: avisa al cruzar, no cada vez
    for rs, op, meta in reglas:
        if rs != sym:
            continue
        ok = (p > meta if op == ">" else p < meta if op == "<"
              else p >= meta if op == ">=" else p <= meta)
        clave = f"{sym}{op}{meta}"
        antes = ESTADO["precios"].get(clave, False)
        if ok and not antes:
            try:
                enviar(f"Alerta {sym} {op} {meta} (ahora {p})", f"Bot 24/7\n{sym} en {p}\n{sym}{op}{meta}\n{datetime.now()}")
                print(f"ALERTA {sym} enviada", flush=True)
            except Exception as e:
                print(f"Error correo: {e}", flush=True)
        if ok != antes:
            marcar(clave, "precios", ok); cambios = True

with open(ESTADO_FILE, "w", encoding="utf-8") as _f:
    _json.dump(ESTADO, _f, ensure_ascii=False)
# En la nube: guarda el estado en el repo para no repetir avisos
if cambios and os.environ.get("GITHUB_ACTIONS") == "true":
    try:
        import subprocess
        _b = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "config", "user.email", "bot@wallstreet"], cwd=_b, timeout=30)
        subprocess.run(["git", "config", "user.name", "bot"], cwd=_b, timeout=30)
        subprocess.run(["git", "add", "estado.json"], cwd=_b, timeout=30)
        subprocess.run(["git", "commit", "-m", "Actualiza estado de alertas"], cwd=_b, timeout=30)
        subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=_b, timeout=120)
    except Exception as e:
        print(f"No se pudo guardar estado: {e}", flush=True)
