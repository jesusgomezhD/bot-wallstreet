"""
BOT WALL STREET - Alertas a correo
En manos de Dios. En el nombre de Jesucristo. Amen.
Alpaca (acciones real) + Finnhub (acciones+forex) + Stooq (gratis sin clave, fallback).

Uso: python bot_alertas.py
Config se guarda en config_bot.json (correo queda guardado).
Para .exe con icono: pip install pyinstaller -> pyinstaller --onefile --windowed --icon=icono.ico bot_alertas.py
"""
import json, os, time, threading, smtplib, csv, io
from email.mime.text import MIMEText
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext
except Exception as e:
    raise SystemExit(f"Falta tkinter: {e}")

try:
    import requests
except ImportError:
    raise SystemExit("Falta requests. Instala con: python -m pip install requests")

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config_bot.json")

DEFAULTS = {
    "correo_destino": "",
    "gmail_remitente": "",
    "gmail_clave_app": "",
    "tickers": "AAPL, SPY, QQQ, EUR/USD",
    "alertas": "AAPL>250, SPY>600, EUR/USD>1.10",
    "finnhub_key": "",
    "alpaca_key": "",
    "alpaca_secret": "",
    "intervalo_seg": 60,
    "umbral_pct": 2,
    "github_token": "",
}

NUBE_FILE = os.path.join(BASE, "config_nube.json")
HIST_FILE = os.path.join(BASE, "historial.json")

def guardar_historial(ticker, tipo, detalle):
    try:
        h = []
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE, encoding="utf-8") as f:
                h = json.load(f)
        h.append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "ticker": ticker,
                  "tipo": tipo, "detalle": detalle})
        with open(HIST_FILE, "w", encoding="utf-8") as f:
            json.dump(h[-500:], f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def historial_agrupado():
    grupos = {}
    try:
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE, encoding="utf-8") as f:
                for e in json.load(f):
                    grupos.setdefault(e.get("ticker", "?"), []).append(e)
    except Exception:
        pass
    return grupos

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                for k, v in DEFAULTS.items():
                    d.setdefault(k, v)
                return d
        except Exception:
            pass
    return dict(DEFAULTS)

def save_config(d):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

# ---------- PRECIOS ----------
def precio_yahoo(symbol):
    """Gratis sin clave. Acciones: AAPL | Forex EUR/USD -> EURUSD=X"""
    s = symbol.strip().upper()
    if "/" in s:
        # EUR/USD -> EURUSD=X
        y = s.replace("/", "") + "=X"
    elif s in ("EURUSD", "EURUSD=X"):
        y = "EURUSD=X"
    else:
        y = s
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    r.raise_for_status()
    j = r.json()
    meta = j["chart"]["result"][0]["meta"]
    p = meta.get("regularMarketPrice")
    return float(p) if p else None

def precio_finnhub(symbol, key):
    if not key:
        return None
    s = symbol.strip().upper().replace("/", "")
    # forex: OANDA:EUR_USD
    if "EURUSD" in s or "EUR" in s:
        sym = "OANDA:EUR_USD" if "EUR" in s else s
    else:
        sym = s
    url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={key}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    j = r.json()
    c = j.get("c")
    return float(c) if c else None

def precio_alpaca(symbol, key, secret):
    if not key or "/" in symbol:
        return None  # Alpaca: solo acciones
    s = symbol.strip().upper()
    url = f"https://data.alpaca.markets/v2/stocks/{s}/trades/latest"
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    r = requests.get(url, headers=h, timeout=10)
    if r.status_code != 200:
        return None
    j = r.json()
    try:
        return float(j["trade"]["p"])
    except Exception:
        return None

def obtener_precio(symbol, cfg):
    # 1. Alpaca (mas rapido acciones) 2. Finnhub 3. Yahoo gratis (verificado 2026)
    try:
        p = precio_alpaca(symbol, cfg.get("alpaca_key",""), cfg.get("alpaca_secret",""))
        if p:
            return p, "Alpaca"
    except Exception:
        pass
    try:
        p = precio_finnhub(symbol, cfg.get("finnhub_key",""))
        if p:
            return p, "Finnhub"
    except Exception:
        pass
    try:
        p = precio_yahoo(symbol)
        if p:
            return p, "Yahoo"
    except Exception:
        pass
    return None, "-"

# ---------- ALERTAS ----------
def parse_alertas(txt):
    """Formato: AAPL>250, SPY<500, EUR/USD>1.10  (una por coma)"""
    out = []
    for part in (txt or "").split(","):
        part = part.strip()
        if not part:
            continue
        for op in (">=", "<=", ">", "<"):
            if op in part:
                sym, val = part.split(op, 1)
                try:
                    out.append((sym.strip().upper(), op, float(val.strip())))
                except ValueError:
                    pass
                break
    return out

def cumple(precio, op, meta):
    return {" >": precio > meta, ">": precio > meta, "<": precio < meta,
            ">=": precio >= meta, "<=": precio <= meta}.get(op, False)

def enviar_correo(cfg, asunto, cuerpo):
    if not cfg["gmail_remitente"] or not cfg["gmail_clave_app"] or not cfg["correo_destino"]:
        return False, "Falta correo remitente/clave/destino"
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = cfg["gmail_remitente"]
    msg["To"] = cfg["correo_destino"]
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.starttls()
        s.login(cfg["gmail_remitente"], cfg["gmail_clave_app"])
        s.sendmail(cfg["gmail_remitente"], [cfg["correo_destino"]], msg.as_string())
    return True, "enviado"

# ---------- GRUPOS DE TICKERS ----------
GRUPOS = [
    ("ACCIONES USA", ["MU","META","MRNA","SPY","QQQ","COST","AMD","CSCO","TSLA","SPCX","AAPL",
     "MSFT","NVDA","AMZN","GOOGL","AVGO","NFLX","PLTR","INTC","QCOM","INTU","AMGN","BKNG",
     "ADBE","MELI","ARM","APP","ABBV","JPM","V","XOM","UNH","MA","JNJ","WMT","PG","ORCL","HD",
     "BAC","CRM","KO","MRK","DIS","LLY","PEP","TMO","ABT","ACN","AXP","BA","CAT","CVX","DHR",
     "GE","GS","HON","IBM","MCD","MS","NEE","NKE","NOW","PFE","RTX","SBUX","T","TXN","UPS",
     "VZ","DIA","IWM","SHOP","SOFI","PYPL","UBER","GILD","DELL","ANET","PANW","CRWD"]),
    ("INDICES", [("SPY","S&P 500 ETF"),("QQQ","Nasdaq 100 ETF"),("DIA","Dow Jones ETF"),
     ("IWM","Russell 2000"),("^GSPC","S&P 500 indice"),("^DJI","Dow Jones indice"),
     ("^IXIC","Nasdaq indice"),("^VIX","Volatilidad")]),
    ("FOREX", [("EUR/USD","Euro-Dolar"),("GBP/USD","Libra-Dolar"),("USD/JPY","Dolar-Yen"),
     ("USD/COP","Dolar-Peso COL"),("USD/MXN","Dolar-Peso MEX"),("USD/BRL","Dolar-Real"),
     ("AUD/USD","Australiano-Dolar"),("USD/CAD","Dolar-Canadiense"),("USD/CHF","Dolar-Franco"),
     ("EUR/GBP","Euro-Libra")]),
    ("ORO Y MATERIAS", [("GLD","Oro"),("SLV","Plata"),("PPLT","Platino"),
     ("USO","Petroleo WTI"),("BNO","Petroleo Brent"),("UNG","Gas natural")]),
]

def _simbolo(item):
    return item[0] if isinstance(item, tuple) else item

def _texto(item):
    return f"{item[0]}  {item[1]}" if isinstance(item, tuple) else item

# ---------- APP ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Bot Wall Street - Alertas | En manos de Dios")
        root.geometry("660x800")
        self.cfg = load_config()
        self.corriendo = False
        self.avisados = set()

        f = tk.Frame(root, padx=12, pady=10)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="BOT WALL STREET - Alertas a correo", font=("Arial", 13, "bold")).pack()
        tk.Label(f, text="Alpaca + Finnhub + Stooq | Acciones y Forex", fg="gray").pack(pady=(0,8))

        self.entries = {}
        def campo(label, key, show=None):
            tk.Label(f, text=label, font=("Arial", 9, "bold")).pack(anchor="w")
            e = tk.Entry(f, width=70, show=show or "")
            e.insert(0, str(self.cfg.get(key, "")))
            e.pack(fill="x")
            self.entries[key] = e

        campo("1) Correo destino (donde te aviso - queda guardado):", "correo_destino")
        campo("2) Tu Gmail remitente:", "gmail_remitente")
        campo("3) Clave de aplicacion Gmail (no tu clave normal):", "gmail_clave_app", show="*")
        campo("4) Tickers que te interesan (separados por coma):", "tickers")
        tk.Label(f, text="Ej: AAPL, SPY, QQQ, NVDA, EUR/USD", fg="gray", font=("Arial", 8)).pack(anchor="w")
        tk.Label(f, text="4b) O elige por grupos (clic para desplegar):", font=("Arial", 9, "bold")).pack(anchor="w", pady=(4,0))
        self._grupos = {}
        for nombre, items in GRUPOS:
            cab = tk.Button(f, text=f"▶ {nombre} ({len(items)})", anchor="w",
                            command=lambda n=nombre: self._grupo_toggle(n))
            cab.pack(fill="x")
            box = tk.Frame(f)
            self._grupos[nombre] = {"items": items, "mostrados": list(items),
                                    "frame": box, "btn": cab, "abierto": False}
            busc = tk.Entry(box, width=70)
            busc.pack(fill="x")
            busc.bind("<KeyRelease>", lambda e, n=nombre: self._grupo_filtrar(n))
            self._grupos[nombre]["busc"] = busc
            lb = tk.Listbox(box, selectmode="multiple", height=6, exportselection=False)
            for it in items:
                lb.insert("end", _texto(it))
            lb.pack(fill="x")
            self._grupos[nombre]["lista"] = lb
            tk.Button(box, text=f"+ Agregar seleccionados al campo",
                      command=lambda n=nombre: self._grupo_agregar(n)).pack(anchor="e")

    def _grupo_toggle(self, nombre):
        g = self._grupos[nombre]
        g["abierto"] = not g["abierto"]
        if g["abierto"]:
            g["frame"].pack(fill="x")
            g["btn"].config(text=f"▼ {nombre} ({len(g['items'])})")
        else:
            g["frame"].pack_forget()
            g["btn"].config(text=f"▶ {nombre} ({len(g['items'])})")

    def _grupo_filtrar(self, nombre):
        g = self._grupos[nombre]
        q = g["busc"].get().strip().upper()
        lb = g["lista"]
        lb.delete(0, "end")
        g["mostrados"] = []
        for it in g["items"]:
            if q in _texto(it).upper():
                lb.insert("end", _texto(it))
                g["mostrados"].append(it)

    def _grupo_agregar(self, nombre):
        g = self._grupos[nombre]
        sel = [_simbolo(g["mostrados"][i]) for i in g["lista"].curselection()
               if i < len(g["mostrados"])]
        if not sel:
            self.msg(f"{nombre}: marca tickers en la lista primero.")
            return
        actual = [t.strip().upper() for t in self.entries["tickers"].get().split(",") if t.strip()]
        for s in sel:
            if s.upper() not in actual:
                actual.append(s.upper())
        self.entries["tickers"].delete(0, "end")
        self.entries["tickers"].insert(0, ",".join(actual))
        self.msg(f"{nombre}: {len(sel)} agregados.")
        campo("5) Avisame cuando (TICKER>precio o TICKER<precio):", "alertas")
        tk.Label(f, text="Ej: AAPL>250, SPY<500, EUR/USD>1.10", fg="gray", font=("Arial", 8)).pack(anchor="w")
        campo("Finnhub API Key (gratis, para forex y acciones):", "finnhub_key")
        campo("Alpaca API Key (gratis, acciones tiempo real):", "alpaca_key")
        campo("Alpaca Secret:", "alpaca_secret", show="*")
        campo("Revisar cada X segundos:", "intervalo_seg")
        campo("6) Umbral auto % (avisa si sube/baja esto en el dia):", "umbral_pct")
        campo("GitHub token (solo este PC, para subir a nube):", "github_token", show="*")

        btns = tk.Frame(f)
        btns.pack(pady=8)
        tk.Button(btns, text="💾 Guardar", command=self.guardar, width=12).pack(side="left", padx=4)
        tk.Button(btns, text="☁ Subir a nube", command=self.subir_nube, width=13, bg="#cce5ff").pack(side="left", padx=4)
        tk.Button(btns, text="▶ Iniciar", command=self.iniciar, width=10, bg="#d4edda").pack(side="left", padx=4)
        tk.Button(btns, text="⏹ Detener", command=self.detener, width=10, bg="#f8d7da").pack(side="left", padx=4)
        tk.Button(btns, text="✉ Probar correo", command=self.probar, width=13).pack(side="left", padx=4)

        self.log = scrolledtext.ScrolledText(f, height=10, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, pady=(6,0))
        self.msg("Listo. 1) Llena tu correo 2) Guarda 3) Inicia. Dios te guarde.")

        tk.Label(f, text="Historial de mis alertas (agrupado por ticker)", font=("Arial", 10, "bold")).pack(anchor="w", pady=(6,0))
        hb = tk.Frame(f)
        hb.pack(fill="x")
        tk.Button(hb, text="Ver historial", command=self.ver_historial, width=14).pack(side="left", padx=4)
        tk.Button(hb, text="Traer nube", command=self.traer_nube, width=14).pack(side="left", padx=4)
        tk.Button(hb, text="⏸ Pausar nube", command=lambda: self.pausa_nube(True), width=14).pack(side="left", padx=4)
        tk.Button(hb, text="▶ Reanudar nube", command=lambda: self.pausa_nube(False), width=14).pack(side="left", padx=4)
        self.hist = scrolledtext.ScrolledText(f, height=8, font=("Consolas", 9))
        self.hist.pack(fill="both", expand=True)

    def ver_historial(self):
        self.cfg = self.leer()
        self.hist.delete("1.0", "end")
        # 1) Pedidas (del formulario), agrupadas por ticker
        ped = {}
        for s, op, m in parse_alertas(self.cfg.get("alertas", "")):
            ped.setdefault(s, []).append(f"{s}{op}{m}")
        self.hist.insert("end", "=== PEDIDAS (mi formulario) ===\n")
        if not ped:
            self.hist.insert("end", "(ninguna con precio; solo auto %)\n")
        for t in sorted(ped):
            self.hist.insert("end", f"[{t}] " + ", ".join(ped[t]) + "\n")
        # 2) Enviadas, agrupadas por ticker
        self.hist.insert("end", "\n=== ENVIADAS (correo) ===\n")
        g = historial_agrupado()
        if not g:
            self.hist.insert("end", "(aun no se ha enviado ninguna desde esta app)\n")
        for t in sorted(g):
            self.hist.insert("end", f"[{t}] ({len(g[t])})\n")
            for e in g[t][-10:]:
                self.hist.insert("end", f"  {e['fecha']} {e['tipo']}: {e['detalle']}\n")

    def pausa_nube(self, pausar):
        import subprocess
        self.cfg = self.leer()
        save_config(self.cfg)
        token = self.cfg.get("github_token", "")
        if not token:
            messagebox.showwarning("Falta token", "El token ya esta guardado en este PC.")
            return
        def run(*a):
            return subprocess.run(a, cwd=BASE, capture_output=True, text=True, timeout=120)
        if pausar:
            with open(os.path.join(BASE, "PAUSADO"), "w", encoding="utf-8") as f:
                f.write("Pausado por el usuario desde la app.")
            run("git", "add", "PAUSADO")
            run("git", "commit", "-m", "Pausa nube")
        else:
            try:
                os.remove(os.path.join(BASE, "PAUSADO"))
            except OSError:
                pass
            run("git", "rm", "-q", "PAUSADO")
            run("git", "commit", "-m", "Reanuda nube")
        r = run("git", "push", f"https://jesusgomezhD:{token}@github.com/jesusgomezhD/bot-wallstreet.git", "main")
        self.msg("Nube " + ("pausada." if pausar else "reanudada.") if r.returncode == 0 else "Error al cambiar estado.")

    def traer_nube(self):
        import subprocess
        try:
            r = subprocess.run(["git", "pull", "origin", "main"], cwd=BASE,
                               capture_output=True, text=True, timeout=120)
        except Exception as e:
            self.msg(f"Error git pull: {e}")
            return
        try:
            with open(os.path.join(BASE, "estado.json"), encoding="utf-8") as fh:
                est = json.load(fh)
        except Exception:
            est = {}
        avis = list(est.get("pct", [])) + [k for k, v in est.get("precios", {}).items() if v]
        self.hist.delete("1.0", "end")
        self.hist.insert("end", f"=== NUBE (avisadas {est.get('fecha', '?')}) ===\n")
        if not avis:
            self.hist.insert("end", "(la nube aun no avisa nada hoy)\n")
        for a in sorted(set(avis)):
            self.hist.insert("end", f"- {a}\n")
            guardar_historial(a.split(">")[0].split("<")[0][:12], "nube", a)
        self.msg("Nube traida: " + (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ok"))

    def msg(self, t):
        h = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{h}] {t}\n")
        self.log.see("end")

    def leer(self):
        d = {k: e.get().strip() for k, e in self.entries.items()}
        try:
            d["intervalo_seg"] = max(15, int(d.get("intervalo_seg", 60)))
        except ValueError:
            d["intervalo_seg"] = 60
        return d

    def guardar(self):
        self.cfg = self.leer()
        save_config(self.cfg)
        self.msg(f"Guardado en {CONFIG_FILE}. Correo destino: {self.cfg['correo_destino']}")
        messagebox.showinfo("Guardado", "Correo y tickers guardados. Ya queda fijo.")

    def probar(self):
        self.cfg = self.leer()
        save_config(self.cfg)
        try:
            ok, m = enviar_correo(self.cfg, "Prueba Bot Wall Street 🙏",
                "Dios te bendiga. Tu bot de alertas quedo configurado correctamente.")
            self.msg(f"Prueba correo: {m}")
            messagebox.showinfo("Correo", m)
        except Exception as e:
            self.msg(f"Error correo: {e}")
            messagebox.showerror("Error", f"{e}\n\nUsa Clave de aplicacion de Gmail, no tu clave normal.")

    def subir_nube(self):
        """El formulario manda: escribe config_nube.json y lo sube a GitHub."""
        import subprocess
        self.cfg = self.leer()
        save_config(self.cfg)
        token = self.cfg.get("github_token", "")
        if not token:
            messagebox.showwarning("Falta token", "Pega tu GitHub token en el campo y pulsa Guardar primero.")
            return
        try:
            umb = float(str(self.cfg.get("umbral_pct", 2)).replace(",", "."))
        except ValueError:
            umb = 2.0
        nube = {"tickers": self.cfg.get("tickers", ""), "alertas": self.cfg.get("alertas", ""),
                "umbral_pct": umb}
        with open(NUBE_FILE, "w", encoding="utf-8") as f:
            json.dump(nube, f, indent=2, ensure_ascii=False)
        self.msg("Subiendo tickers a la nube...")
        def run(*a):
            return subprocess.run(a, cwd=BASE, capture_output=True, text=True, timeout=120)
        run("git", "add", "config_nube.json")
        run("git", "commit", "-m", "Actualiza alertas desde la app")
        r = run("git", "push", f"https://jesusgomezhD:{token}@github.com/jesusgomezhD/bot-wallstreet.git", "main")
        if r.returncode == 0:
            self.msg("Nube actualizada. El bot 24/7 usara estos tickers.")
            messagebox.showinfo("Nube", "Subido. La nube usara estos tickers y alertas.")
        else:
            self.msg(f"Error al subir: {(r.stderr or r.stdout)[-300:]}")
            messagebox.showerror("Error", "No se pudo subir. Revisa el token.")

    def iniciar(self):
        if self.corriendo:
            return
        self.cfg = self.leer()
        save_config(self.cfg)
        if not self.cfg["correo_destino"]:
            messagebox.showwarning("Falta correo", "Ingresa el correo destino primero y pulsa Guardar.")
            return
        self.corriendo = True
        self.msg(f"Monitoreando: {self.cfg['tickers']} cada {self.cfg['intervalo_seg']}s...")
        threading.Thread(target=self.bucle, daemon=True).start()

    def detener(self):
        self.corriendo = False
        self.msg("Detenido.")

    def bucle(self):
        while self.corriendo:
            try:
                tickers = [t.strip().upper() for t in self.cfg["tickers"].split(",") if t.strip()]
                reglas = parse_alertas(self.cfg["alertas"])
                for sym in tickers:
                    precio, fuente = obtener_precio(sym, self.cfg)
                    if precio is None:
                        self.msg(f"{sym}: sin dato (revisa keys o internet)")
                        continue
                    self.msg(f"{sym}: {precio} ({fuente})")
                    for rsym, op, meta in reglas:
                        if rsym == sym and cumple(precio, op, meta):
                            clave = f"{sym}{op}{meta}"
                            if clave in self.avisados:
                                continue
                            self.avisados.add(clave)
                            asunto = f"🚨 Alerta {sym} {op} {meta} (ahora {precio})"
                            cuerpo = f"Bot Wall Street 🙏\n\n{sym} esta en {precio}\nCondicion: {sym} {op} {meta}\nFuente: {fuente}\nHora: {datetime.now()}\n\nEn manos de Dios."
                            try:
                                enviar_correo(self.cfg, asunto, cuerpo)
                                self.msg(f"ALERTA enviada: {asunto}")
                                guardar_historial(sym, "precio", f"{sym}{op}{meta} -> {precio}")
                            except Exception as e:
                                self.msg(f"No se pudo enviar correo: {e}")
                # limpiar avisos si el precio volvio (para re-avisar luego)
                time.sleep(self.cfg["intervalo_seg"])
            except Exception as e:
                self.msg(f"Error bucle: {e}")
                time.sleep(10)

if __name__ == "__main__":
    r = tk.Tk()
    App(r)
    r.mainloop()
