"""BOT SERVER 24/7 - Backend de alertas. Corre en la nube (Render gratis).
Lee alertas.json del repo cada 60s, vigila, envia correo, guarda estado.
La app de escritorio solo crea/borra alertas y este servidor las ejecuta solo.

Env vars: GMAIL_REMITENTE, GMAIL_CLAVE_APP, GH_TOKEN, REPO, PORT, FINNHUB_KEY
"""
import os, json, time, smtplib, threading, base64
from email.mime.text import MIMEText
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REPO = os.environ.get("REPO", "jesusgomezhD/bot-wallstreet")
PORT = int(os.environ.get("PORT", "10000"))
REM = os.environ.get("GMAIL_REMITENTE", "")
PWD = os.environ.get("GMAIL_CLAVE_APP", "")
TOKEN = os.environ.get("GH_TOKEN", "")
FH = os.environ.get("FINNHUB_KEY", "")
TD = os.environ.get("TWELVEDATA_KEY", "")
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
API = f"https://api.github.com/repos/{REPO}/contents"

estado = {"fecha": "", "avisadas": {}, "ultima_revision": "", "errores": []}

def log(t):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {t}", flush=True)

def gh_get(path):
    r = requests.get(f"{RAW}/{path}?t={int(time.time())}", timeout=20)
    return r.json() if r.status_code == 200 else None

def gh_raw_ok(path):
    try:
        return requests.get(f"{RAW}/{path}?t={int(time.time())}", timeout=15).status_code == 200
    except Exception:
        return False

def gh_put(path, data, msg):
    if not TOKEN:
        return False
    h = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        g = requests.get(f"{API}/{path}", headers=h, timeout=20).json()
        body = {"message": msg,
                "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode()}
        if g.get("sha"):
            body["sha"] = g["sha"]
        r = requests.put(f"{API}/{path}", headers=h, json=body, timeout=30)
        return r.status_code in (200, 201)
    except Exception as e:
        log(f"gh_put error: {e}")
        return False

def precio_yahoo(sym):
    s = sym.strip().upper()
    y = s.replace("/", "") + "=X" if "/" in s else s
    if s == "EURUSD":
        y = "EURUSD=X"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    m = r.json()["chart"]["result"][0]["meta"]
    return float(m["regularMarketPrice"]), float(m.get("chartPreviousClose") or m.get("previousClose") or 0) or None

def precio_finnhub(sym):
    if not FH:
        return None
    s = sym.strip().upper()
    q = "OANDA:EUR_USD" if "EUR" in s else s
    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={q}&token={FH}", timeout=12)
    c = r.json().get("c")
    return (float(c), None) if c else None

def precio_twelve(sym):
    if not TD:
        return None
    r = requests.get(f"https://api.twelvedata.com/price?symbol={sym.strip().upper()}&apikey={TD}",
                     timeout=10)
    j = r.json()
    return (float(j["price"]), None) if j.get("price") else None

def obtener(sym):
    for fn in (precio_finnhub, precio_twelve, precio_yahoo):
        try:
            r = fn(sym)
            if r and r[0]:
                return r
        except Exception:
            pass
    return None, None

def decimales(txt):
    txt = str(txt).strip()
    return len(txt.split(".")[1]) if "." in txt else 0

def cumple(sym, op, objetivo_txt, precio):
    try:
        obj = float(str(objetivo_txt).replace(",", "."))
    except ValueError:
        return False
    if op == "==":
        d = decimales(objetivo_txt)
        return round(precio, d) == round(obj, d)
    if op == ">=":
        return precio >= obj
    if op == "<=":
        return precio <= obj
    if op == ">":
        return precio > obj
    if op == "<":
        return precio < obj
    return False

def nombre_cond(op):
    return {"==": "Igual a", ">=": "Igual o mayor que", "<=": "Igual o menor que",
            ">": "Mayor que", "<": "Menor que"}.get(op, op)

def enviar(dest, asunto, cuerpo):
    m = MIMEText(cuerpo, "plain", "utf-8")
    m["Subject"] = asunto
    m["From"] = REM
    m["To"] = dest
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as s:
        s.starttls()
        s.login(REM, PWD)
        s.sendmail(REM, [dest], m.as_string())

def revisar():
    global estado
    hoy = datetime.now().strftime("%Y-%m-%d")
    cfg = gh_get("alertas.json") or {}
    alertas = cfg.get("alertas", [])
    umbral = float(cfg.get("umbral_pct", 10) or 10)
    dest_default = cfg.get("correo_destino", "")
    if estado.get("fecha") != hoy:
        estado = {"fecha": hoy, "avisadas": {}, "ultima_revision": "", "errores": []}
    if gh_raw_ok("PAUSADO"):
        estado["ultima_revision"] = datetime.now().strftime("%H:%M:%S") + " (pausado)"
        return
    for a in alertas:
        aid = a.get("id", "")
        if a.get("estado", "activa") != "activa" or not aid:
            continue
        sym = a.get("ticker", "").upper()
        dest = a.get("correo") or dest_default
        if not sym or not dest:
            continue
        p, previo = obtener(sym)
        if p is None:
            estado["errores"].append(f"{hoy} {sym}: sin precio")
            continue
        # 1) condicion de precio de la alerta
        if a.get("op") and a.get("precio") not in (None, ""):
            if cumple(sym, a["op"], a["precio"], p) and f"p:{aid}" not in estado["avisadas"]:
                try:
                    enviar(dest, f"Tu alerta se activo: {sym} en {p}",
                           f"Tu alerta se activo.\n\n{sym} acaba de alcanzar {p}.\n"
                           f"Condicion configurada: {nombre_cond(a['op'])} {a['precio']}.\n"
                           f"Fecha y hora: {datetime.now():%Y-%m-%d %H:%M}.\n"
                           f"Precio detectado: {p}.")
                    estado["avisadas"][f"p:{aid}"] = {"fecha": hoy, "precio": p}
                    a["estado"] = "activada"
                    a["ultima_activacion"] = f"{hoy} {p}"
                    log(f"ACTIVADA {sym} {a['op']}{a['precio']} -> {p}")
                except Exception as e:
                    estado["errores"].append(f"{hoy} {sym}: error correo {e}")
        # 2) aviso auto por % del dia
        if previo and umbral > 0:
            pct = round((p - previo) / previo * 100, 2)
            if abs(pct) >= umbral and f"u:{sym}" not in estado["avisadas"]:
                try:
                    enviar(dest, f"{sym} {pct:+}% en el dia (ahora {p})",
                           f"Bot 24/7\n{sym} en {p}\nCambio del dia: {pct:+}% (umbral {umbral}%).\n"
                           f"Fecha y hora: {datetime.now():%Y-%m-%d %H:%M}.")
                    estado["avisadas"][f"u:{sym}"] = {"fecha": hoy, "precio": p}
                    log(f"AUTO {sym} {pct:+}%")
                except Exception as e:
                    estado["errores"].append(f"{hoy} {sym}: error correo {e}")
    estado["ultima_revision"] = datetime.now().strftime("%H:%M:%S")
    gh_put("estado_server.json", estado, "Estado del servidor")
    # persiste activadas en alertas.json (idempotencia real)
    if any(x.get("estado") == "activada" for x in alertas):
        gh_put("alertas.json", cfg, "Marca alertas activadas")

def loop():
    # recupera estado al arrancar (recuperacion ante fallas)
    prev = gh_get("estado_server.json")
    if isinstance(prev, dict) and prev.get("fecha") == datetime.now().strftime("%Y-%m-%d"):
        estado.update(prev)
        log("Estado recuperado del dia.")
    while True:
        try:
            revisar()
        except Exception as e:
            log(f"Error revision: {e}")
        time.sleep(60)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"ok": True, "servicio": "bot-wallstreet 24/7",
                "ultima_revision": estado.get("ultima_revision"),
                "avisadas_hoy": len(estado.get("avisadas", {}))}.__str__()
        if self.path == "/estado":
            body = json.dumps({"estado": "activa",
                               "ultima_revision": estado.get("ultima_revision"),
                               "avisadas": estado.get("avisadas", {})})
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    log(f"Servidor 24/7 en puerto {PORT}.")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
