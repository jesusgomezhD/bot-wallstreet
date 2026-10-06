"""
BOT WALL STREET - App simple
En manos de Dios. En el nombre de Jesucristo. Amen.
Flujo: eliges ticker por grupos -> le pones alerta -> Subir a nube -> avisa 24/7.
"""
import json, os, subprocess, smtplib, threading, time
from email.mime.text import MIMEText
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, scrolledtext
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config_bot.json")
NUBE_FILE = os.path.join(BASE, "config_nube.json")
HIST_FILE = os.path.join(BASE, "historial.json")

DEFAULTS = {"correo_destino": "", "gmail_remitente": "", "gmail_clave_app": "",
            "alertas": "", "umbral_pct": 10, "github_token": "",
            "tickers": ""}

GRUPOS = [
    ("ACCIONES USA", ["MU","META","MRNA","SPY","QQQ","COST","AMD","CSCO","TSLA","SPCX","AAPL",
     "MSFT","NVDA","AMZN","GOOGL","AVGO","NFLX","PLTR","INTC","QCOM","INTU","AMGN","BKNG",
     "ADBE","MELI","ARM","APP","ABBV","JPM","V","XOM","UNH","MA","JNJ","WMT","PG","ORCL","HD",
     "BAC","CRM","KO","MRK","DIS","LLY","PEP","TMO","ABT","ACN","AXP","BA","CAT","CVX","DHR",
     "GE","GS","HON","IBM","MCD","MS","NEE","NKE","NOW","PFE","RTX","SBUX","T","TXN","UPS",
     "VZ","DIA","IWM","SHOP","SOFI","PYPL","UBER","GILD","DELL","ANET","PANW","CRWD"]),
    ("INDICES", [("SPY","S&P 500 ETF"),("QQQ","Nasdaq 100 ETF"),("DIA","Dow Jones ETF"),
     ("IWM","Russell 2000"),("^GSPC","S&P 500"),("^DJI","Dow Jones"),("^IXIC","Nasdaq"),("^VIX","Volatilidad")]),
    ("FOREX", [("EUR/USD","Euro-Dolar"),("GBP/USD","Libra-Dolar"),("USD/JPY","Dolar-Yen"),
     ("USD/COP","Dolar-Peso COL"),("USD/MXN","Dolar-Peso MEX"),("USD/BRL","Dolar-Real"),
     ("AUD/USD","Australiano-Dolar"),("USD/CAD","Dolar-Canadiense"),("USD/CHF","Dolar-Franco"),
     ("EUR/GBP","Euro-Libra")]),
    ("ORO Y MATERIAS", [("GLD","Oro"),("SLV","Plata"),("PPLT","Platino"),
     ("USO","Petroleo WTI"),("BNO","Petroleo Brent"),("UNG","Gas natural")]),
]

def _sim(it):
    return it[0] if isinstance(it, tuple) else it

def _txt(it):
    return f"{it[0]}  {it[1]}" if isinstance(it, tuple) else it

def load_config():
    d = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            d.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except Exception:
            pass
    return d

def save_config(d):
    json.dump(d, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

def parse_alertas(txt):
    out = []
    for part in (txt or "").split(","):
        part = part.strip()
        if not part:
            continue
        for op in (">=", "<=", ">", "<"):
            if op in part:
                s, v = part.split(op, 1)
                try:
                    out.append((s.strip().upper(), op, float(v.strip())))
                except ValueError:
                    pass
                break
    return out

def guardar_historial(ticker, tipo, detalle):
    try:
        h = json.load(open(HIST_FILE, encoding="utf-8")) if os.path.exists(HIST_FILE) else []
        h.append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                  "ticker": ticker, "tipo": tipo, "detalle": detalle})
        json.dump(h[-500:], open(HIST_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("Bot Wall Street | En manos de Dios")
        root.geometry("560x720")
        self.cfg = load_config()
        self.seleccionado = None

        f = tk.Frame(root, padx=14, pady=10)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="BOT WALL STREET", font=("Arial", 14, "bold")).pack()
        tk.Label(f, text="Elige ticker, ponle alerta, súbelo. La nube avisa 24/7.",
                 fg="gray", font=("Arial", 9)).pack(pady=(0, 6))

        # 1) Ticker por grupos
        tk.Label(f, text="1) Elige el ticker", font=("Arial", 10, "bold")).pack(anchor="w")
        self._grupos = {}
        for nombre, items in GRUPOS:
            b = tk.Button(f, text=f"▶ {nombre} ({len(items)})", anchor="w",
                          command=lambda n=nombre: self._toggle(n))
            b.pack(fill="x")
            box = tk.Frame(f)
            self._grupos[nombre] = {"items": items, "mostrados": list(items),
                                    "frame": box, "btn": b}
            s = tk.Entry(box)
            s.pack(fill="x")
            s.bind("<KeyRelease>", lambda e, n=nombre: self._filtrar(n))
            self._grupos[nombre]["busc"] = s
            lb = tk.Listbox(box, height=5, exportselection=False)
            for it in items:
                lb.insert("end", _txt(it))
            lb.pack(fill="x")
            lb.bind("<<ListboxSelect>>", lambda e, n=nombre: self._elegir(n))
            self._grupos[nombre]["lista"] = lb

        self.sel_label = tk.Label(f, text="Seleccionado: (ninguno)",
                                  font=("Arial", 11, "bold"), fg="#0a58ca")
        self.sel_label.pack(anchor="w", pady=(6, 0))

        # 2) Ponle alerta
        tk.Label(f, text="2) Ponle la alerta", font=("Arial", 10, "bold")).pack(anchor="w", pady=(4, 0))
        fa = tk.Frame(f)
        fa.pack(fill="x")
        self.cond = tk.StringVar(value=">")
        tk.OptionMenu(fa, self.cond, ">", "<", ">=", "<=").pack(side="left")
        tk.Label(fa, text=" precio: ").pack(side="left")
        self.precio = tk.Entry(fa, width=14)
        self.precio.pack(side="left")
        tk.Button(fa, text="+ Agregar alerta", command=self.agregar_alerta,
                  bg="#d4edda").pack(side="left", padx=6)

        # 3) Mis alertas (activas: cada una con su boton borrar)
        tk.Label(f, text="3) Mis alertas activas", font=("Arial", 10, "bold")).pack(anchor="w", pady=(4, 0))
        self.alertas_frame = tk.Frame(f)
        self.alertas_frame.pack(fill="x")

        # Botones
        bb = tk.Frame(f)
        bb.pack(pady=6)
        tk.Button(bb, text="☁ Subir a nube", command=self.subir_nube,
                  bg="#cce5ff", width=13).pack(side="left", padx=3)
        tk.Button(bb, text="📜 Historial", command=self.ver_historial, width=11).pack(side="left", padx=3)
        tk.Button(bb, text="⏸ Pausar", command=lambda: self.pausa(True), width=9).pack(side="left", padx=3)
        tk.Button(bb, text="▶ Seguir", command=lambda: self.pausa(False), width=9).pack(side="left", padx=3)
        tk.Button(bb, text="⚡ Rápido", command=self.modo_rapido, width=9).pack(side="left", padx=3)
        tk.Button(bb, text="⚙", command=self.configurar, width=3).pack(side="left", padx=3)

        self.log = scrolledtext.ScrolledText(f, height=5, font=("Consolas", 8), fg="gray")
        self.log.pack(fill="both", expand=True)
        self.refrescar_alertas()
        self.msg("Elige un ticker arriba para empezar.")

    # ----- grupos -----
    def _toggle(self, nombre):
        g = self._grupos[nombre]
        abierto = g["frame"].winfo_ismapped()
        if abierto:
            g["frame"].pack_forget()
            g["btn"].config(text=f"▶ {nombre} ({len(g['items'])})")
        else:
            g["frame"].pack(fill="x")
            g["btn"].config(text=f"▼ {nombre} ({len(g['items'])})")

    def _filtrar(self, nombre):
        g = self._grupos[nombre]
        q = g["busc"].get().strip().upper()
        lb = g["lista"]
        lb.delete(0, "end")
        g["mostrados"] = []
        for it in g["items"]:
            if q in _txt(it).upper():
                lb.insert("end", _txt(it))
                g["mostrados"].append(it)

    def _elegir(self, nombre):
        g = self._grupos[nombre]
        sel = g["lista"].curselection()
        if not sel or sel[0] >= len(g["mostrados"]):
            return
        self.seleccionado = _sim(g["mostrados"][sel[0]])
        self.sel_label.config(text=f"Seleccionado: {self.seleccionado} (buscando precio...)")
        import threading
        threading.Thread(target=self._precio_actual, args=(self.seleccionado,),
                         daemon=True).start()

    def _precio_actual(self, sym):
        try:
            y = sym.replace("/", "") + "=X" if "/" in sym else sym
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
            p = float(r["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if sym == self.seleccionado:
                self.sel_label.config(text=f"Seleccionado: {sym} (ahora {p})")
        except Exception:
            if sym == self.seleccionado:
                self.sel_label.config(text=f"Seleccionado: {sym}")

    # ----- alertas -----
    def agregar_alerta(self):
        if not self.seleccionado:
            messagebox.showwarning("Ticker", "Primero elige un ticker de los grupos.")
            return
        try:
            p = float(self.precio.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Precio", "Escribe el precio, ej: 250")
            return
        reglas = parse_alertas(self.cfg.get("alertas", ""))
        clave = (self.seleccionado, self.cond.get(), p)
        if clave in reglas:
            messagebox.showinfo("Listo", "Esa alerta ya existe.")
            return
        reglas.append(clave)
        self.cfg["alertas"] = ",".join(f"{s}{o}{m:g}" for s, o, m in reglas)
        save_config(self.cfg)
        self.refrescar_alertas()
        self.msg(f"Alerta: {self.seleccionado}{self.cond.get()}{p:g}. Dale Subir a nube.")
        self.precio.delete(0, "end")

    def quitar_alerta(self, idx):
        reglas = parse_alertas(self.cfg.get("alertas", ""))
        if 0 <= idx < len(reglas):
            fuera = reglas.pop(idx)
            self.cfg["alertas"] = ",".join(f"{s}{o}{m:g}" for s, o, m in reglas)
            save_config(self.cfg)
            self.refrescar_alertas()
            self.msg(f"Quitada: {fuera[0]}{fuera[1]}{fuera[2]:g}")

    def refrescar_alertas(self):
        reglas = parse_alertas(self.cfg.get("alertas", ""))
        for w in self.alertas_frame.winfo_children():
            w.destroy()
        grupos = {}
        for i, (s, o, m) in enumerate(reglas):
            grupos.setdefault(s, []).append((i, f"{s}{o}{m:g}"))
        if not grupos:
            tk.Label(self.alertas_frame, text="(sin alertas con precio: solo aviso auto)",
                     fg="gray", font=("Arial", 9)).pack(anchor="w")
            return
        for t in sorted(grupos):
            tk.Label(self.alertas_frame, text=f"[{t}]",
                     font=("Arial", 9, "bold")).pack(anchor="w")
            for i, txt in grupos[t]:
                fila = tk.Frame(self.alertas_frame)
                fila.pack(fill="x", padx=12)
                tk.Label(fila, text=f"• {txt}", font=("Consolas", 9)).pack(side="left")
                tk.Button(fila, text="Borrar alerta", fg="red",
                          command=lambda j=i: self.quitar_alerta(j)).pack(side="right")

    # ----- historial -----
    def ver_historial(self):
        top = tk.Toplevel(self.root)
        top.title("Historial de alertas")
        top.geometry("480x420")
        t = scrolledtext.ScrolledText(top, font=("Consolas", 9))
        t.pack(fill="both", expand=True, padx=8, pady=8)
        try:
            h = json.load(open(HIST_FILE, encoding="utf-8")) if os.path.exists(HIST_FILE) else []
        except Exception:
            h = []
        g = {}
        for e in h:
            g.setdefault(e.get("ticker", "?"), []).append(e)
        if not g:
            t.insert("end", "(aún no se envía ninguna desde esta app)\n")
        for ticker in sorted(g):
            t.insert("end", f"[{ticker}] ({len(g[ticker])})\n")
            for e in g[ticker][-15:]:
                t.insert("end", f"  {e['fecha']} {e['tipo']}: {e['detalle']}\n")
        t.insert("end", "\n--- Nube (hoy) ---\n")
        try:
            import subprocess
            subprocess.run(["git", "pull", "-q", "origin", "main"], cwd=BASE, timeout=60,
                           capture_output=True)
            est = json.load(open(os.path.join(BASE, "estado.json"), encoding="utf-8"))
            avis = list(est.get("pct", [])) + [k for k, v in est.get("precios", {}).items() if v]
            t.insert("end", "\n".join(f"- {a}" for a in sorted(set(avis))) or "(nada hoy)")
        except Exception as e:
            t.insert("end", f"(sin conexión a nube: {e})")

    # ----- modo rapido (este PC, ~1 min) -----
    def modo_rapido(self):
        if getattr(self, "rapido", False):
            self.rapido = False
            self.msg("Modo rápido detenido.")
            return
        if not self.cfg.get("gmail_remitente") or not self.cfg.get("gmail_clave_app"):
            messagebox.showwarning("Correo", "Abre ⚙ y pon tu Gmail y clave primero.")
            return
        self.rapido = True
        self._avisados = set()
        self.msg("Modo rápido: revisa cada 60s mientras la app esté abierta.")
        threading.Thread(target=self._loop_rapido, daemon=True).start()

    def _loop_rapido(self):
        import requests as _rq
        while getattr(self, "rapido", False):
            try:
                reglas = parse_alertas(self.cfg.get("alertas", ""))
                vistos = set()
                for sym, op, meta in reglas:
                    y = sym.replace("/", "") + "=X" if "/" in sym else sym
                    try:
                        r = _rq.get(
                            f"https://query1.finance.yahoo.com/v8/finance/chart/{y}?interval=1d&range=1d",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
                        p = float(r["chart"]["result"][0]["meta"]["regularMarketPrice"])
                    except Exception:
                        continue
                    ok = (p > meta if op == ">" else p < meta if op == "<"
                          else p >= meta if op == ">=" else p <= meta)
                    clave = f"{sym}{op}{meta}"
                    vistos.add((clave, ok))
                    if ok and clave not in self._avisados:
                        self._avisados.add(clave)
                        try:
                            m = MIMEText(f"Rapido\n{sym} en {p}\n{sym}{op}{meta}\n{datetime.now()}",
                                         "plain", "utf-8")
                            m["Subject"] = f"Alerta {sym} {op} {meta} (ahora {p})"
                            m["From"] = self.cfg["gmail_remitente"]
                            m["To"] = self.cfg["correo_destino"]
                            s = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
                            s.starttls()
                            s.login(self.cfg["gmail_remitente"], self.cfg["gmail_clave_app"])
                            s.sendmail(self.cfg["gmail_remitente"],
                                       [self.cfg["correo_destino"]], m.as_string())
                            try:
                                s.quit()
                            except Exception:
                                pass
                            self.msg(f"RAPIDA enviada: {sym} {p}")
                            guardar_historial(sym, "rapida", f"{sym}{op}{meta} -> {p}")
                        except Exception as e:
                            self.msg(f"Error correo: {e}")
                # solo recuerda las que siguen cumplidas (re-avisa si vuelve a cruzar)
                self._avisados = {c for c, ok in vistos if ok}
                time.sleep(60)
            except Exception as e:
                self.msg(f"Error rapido: {e}")
                time.sleep(15)

    # ----- nube -----
    def _git(self, *a):
        return subprocess.run(list(a), cwd=BASE, capture_output=True, text=True, timeout=120)

    def subir_nube(self):
        token = self.cfg.get("github_token", "")
        if not token:
            messagebox.showwarning("Token", "Abre ⚙ y pega tu GitHub token una vez.")
            return
        if not self.cfg.get("correo_destino"):
            messagebox.showwarning("Correo", "Abre ⚙ y pon tu correo primero.")
            return
        ticks = sorted({s for s, _, _ in parse_alertas(self.cfg.get("alertas", ""))})
        base = [t.strip().upper() for t in self.cfg.get("tickers", "").split(",") if t.strip()]
        nube = {"tickers": ",".join(sorted(set(ticks + base))) or ",".join(ticks),
                "alertas": self.cfg.get("alertas", ""),
                "umbral_pct": self.cfg.get("umbral_pct", 10),
                "correo_destino": self.cfg.get("correo_destino", "")}
        json.dump(nube, open(NUBE_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        self.msg("Subiendo...")
        self._git("git", "add", "config_nube.json")
        self._git("git", "commit", "-m", "Actualiza alertas desde la app")
        r = self._git("git", "push",
                      f"https://jesusgomezhD:{token}@github.com/jesusgomezhD/bot-wallstreet.git", "main")
        if r.returncode == 0:
            self.msg("Nube actualizada: avisa 24/7 con tus alertas.")
            messagebox.showinfo("Nube", "Listo. La nube usa tus alertas.")
        else:
            self.msg("Error al subir. Revisa el token en ⚙.")

    def pausa(self, pausar):
        token = self.cfg.get("github_token", "")
        if not token:
            messagebox.showwarning("Token", "Abre ⚙ y pega tu GitHub token una vez.")
            return
        if pausar:
            open(os.path.join(BASE, "PAUSADO"), "w", encoding="utf-8").write("Pausado desde la app.")
            self._git("git", "add", "PAUSADO")
            self._git("git", "commit", "-m", "Pausa nube")
        else:
            try:
                os.remove(os.path.join(BASE, "PAUSADO"))
            except OSError:
                pass
            self._git("git", "rm", "-q", "PAUSADO")
            self._git("git", "commit", "-m", "Reanuda nube")
        r = self._git("git", "push",
                      f"https://jesusgomezhD:{token}@github.com/jesusgomezhD/bot-wallstreet.git", "main")
        self.msg("Nube " + ("pausada." if pausar else "reanudada.") if r.returncode == 0
                 else "Error. Revisa el token en ⚙.")

    # ----- config -----
    def configurar(self):
        top = tk.Toplevel(self.root)
        top.title("Config (una sola vez)")
        top.geometry("460x380")
        ents = {}
        for key, label, show in [
                ("correo_destino", "Correo donde te aviso:", ""),
                ("gmail_remitente", "Gmail que envía:", ""),
                ("gmail_clave_app", "Clave de aplicación Gmail:", "*"),
                ("umbral_pct", "Aviso auto si se mueve % en el día:", ""),
                ("github_token", "GitHub token:", "*")]:
            tk.Label(top, text=label, font=("Arial", 9, "bold")).pack(anchor="w", padx=10)
            e = tk.Entry(top, width=55, show=show)
            e.insert(0, str(self.cfg.get(key, "")))
            e.pack(fill="x", padx=10)
            ents[key] = e

        def guardar():
            for k, e in ents.items():
                self.cfg[k] = e.get().strip()
            save_config(self.cfg)
            top.destroy()
            self.msg("Config guardada.")
        tk.Button(top, text="Guardar", command=guardar, bg="#d4edda").pack(pady=10)

    def msg(self, t):
        h = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{h}] {t}\n")
        self.log.see("end")


if __name__ == "__main__":
    try:
        r = tk.Tk()
        App(r)
        r.mainloop()
    except Exception as e:
        import traceback
        open(os.path.join(BASE, "error.log"), "a", encoding="utf-8").write(
            f"\n{datetime.now()}\n{traceback.format_exc()}")
        raise
