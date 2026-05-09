#!/usr/bin/env python3
"""
VMC Control Center Desktop v2
Máquinas expendedoras · csmology.com
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading, urllib.request, urllib.error
import json, time, math, base64, struct
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════
API   = "https://api.vmc002.csmology.com"
TZ    = timezone(timedelta(hours=-6))

import os, sys, webbrowser

# ── ARCHIVO DE TOKEN (el usuario lo pega ahí)
# Buscar token.txt junto al script o ejecutable
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.txt")

_token_lock = threading.Lock()
_current_token = {"value": None}

def load_token_from_file():
    """Lee el token desde token.txt. El usuario lo pega ahí desde el navegador."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t = f.read().strip()
        if not t:
            return None
        if not t.startswith("Bearer "):
            t = "Bearer " + t
        return t
    except Exception:
        return None

def save_token_to_file(token):
    """Guarda el token en token.txt para usarlo después."""
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token if token.startswith("Bearer ") else "Bearer " + token)
        return True
    except Exception as e:
        print(f"Error guardando token: {e}")
        return False

# ── Paleta de colores ───────────────────────────────────
C = {
    "bg":      "#0a0d13",
    "s1":      "#111520",
    "s2":      "#171c2a",
    "s3":      "#1e2436",
    "border":  "#252d42",
    "accent":  "#00d4aa",
    "blue":    "#4d9fff",
    "orange":  "#ff8c42",
    "red":     "#ff5c72",
    "yellow":  "#ffd166",
    "purple":  "#b388ff",
    "green":   "#69db7c",
    "text":    "#ccd6f6",
    "bright":  "#f0f4ff",
    "muted":   "#5a6a8a",
    "card_bg": "#0f1420",
}

CMDS = {
    "0100": ("Normal Service",   "✅", False, C["green"]),
    "0101": ("Out of Service",   "⚠️", True,  C["orange"]),
    "0301": ("Shutdown",         "⏻",  True,  C["red"]),
    "0302": ("Reboot",           "🔄", True,  C["red"]),
    "0307": ("Restart Software", "🔁", False, C["blue"]),
    "0401": ("Upgrade",          "⬆️", True,  C["purple"]),
}

# ══════════════════════════════════════════════════════════
#  API CLIENT
# ══════════════════════════════════════════════════════════
class API_Client:
    def __init__(self):
        pass

    def _get_token(self):
        """Devuelve el token activo, renovándolo si expiró."""
        with _token_lock:
            now = time.time()
            if _current_token["value"] and _current_token["expires"] > now + 60:
                return _current_token["value"]
            # Necesita (re)login
            tok = self._do_login()
            if tok:
                _current_token["value"]   = tok
                # JWT expira en ~2h generalmente; renovar cada 90min
                _current_token["expires"] = now + 90 * 60
            return _current_token["value"]

    def _do_login(self):
        """Hace login completo: obtiene captcha, cifra contraseña, obtiene token."""
        try:
            # 1. Obtener UUID del captcha (no necesitamos resolver la imagen)
            cap_r = urllib.request.Request(API + "/auth/code", method="GET")
            with urllib.request.urlopen(cap_r, timeout=10) as resp:
                cap_data = json.loads(resp.read().decode())
            uuid = cap_data.get("uuid") or cap_data.get("key") or ""

            # 2. Cifrar contraseña con RSA
            enc_pass = rsa_encrypt(PASSWORD)

            # 3. Login SIN captcha (code vacío — muchos servidores lo permiten para
            #    clientes de confianza; si falla, ver nota abajo)
            login_body = json.dumps({
                "username": USERNAME,
                "password": enc_pass,
                "code":     "",
                "uuid":     uuid
            }).encode()
            login_r = urllib.request.Request(
                API + "/auth/login", data=login_body, method="POST")
            login_r.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(login_r, timeout=15) as resp:
                login_data = json.loads(resp.read().decode())

            token = login_data.get("token") or login_data.get("access_token") or                     (login_data.get("data") or {}).get("token")
            if token:
                if not token.startswith("Bearer "):
                    token = "Bearer " + token
                return token
            return None
        except Exception as e:
            print(f"[Login error] {e}")
            return None

    def req(self, method, path, body=None):
        token = self._get_token()
        if not token:
            return {"error": "Sin token — verifica usuario/contraseña"}
        url  = API + path
        data = json.dumps(body).encode() if body is not None else None
        r    = urllib.request.Request(url, data=data, method=method)
        r.add_header("Content-Type",  "application/json")
        r.add_header("Authorization", token)
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                return result
        except urllib.error.HTTPError as e:
            # 401 = token expirado → forzar re-login
            if e.code == 401:
                with _token_lock:
                    _current_token["value"]   = None
                    _current_token["expires"] = 0
                # Reintentar una vez
                token2 = self._get_token()
                if token2:
                    r2 = urllib.request.Request(url, data=data, method=method)
                    r2.add_header("Content-Type",  "application/json")
                    r2.add_header("Authorization", token2)
                    try:
                        with urllib.request.urlopen(r2, timeout=15) as resp2:
                            return json.loads(resp2.read().decode())
                    except Exception as e2:
                        return {"error": str(e2)}
            try:    return json.loads(e.read().decode())
            except: return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _periods(self, mode):
        """
        Genera timePeriodList según el modo:
          'day'   → hoy
          'week'  → últimos 7 días (un objeto por día)
          'month' → este mes completo (un objeto)
        Siempre incluye el resumen global como primer elemento.
        """
        now = datetime.now(TZ)
        fmt = "%Y-%m-%dT%H:%M:%S-06:00"
        periods = []
        if mode == "day":
            s = datetime(now.year, now.month, now.day, 0,  0,  0, tzinfo=TZ)
            e = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=TZ)
            periods.append({"startTime": s.strftime(fmt), "endTime": e.strftime(fmt)})
        elif mode == "week":
            for i in range(6, -1, -1):
                d   = now - timedelta(days=i)
                s   = datetime(d.year, d.month, d.day, 0,  0,  0, tzinfo=TZ)
                e   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)
                periods.append({"startTime": s.strftime(fmt), "endTime": e.strftime(fmt)})
        elif mode == "month":
            s = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=TZ)
            e = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=TZ)
            periods.append({"startTime": s.strftime(fmt), "endTime": e.strftime(fmt)})
        return periods

    def get_stats(self, mode="day"):
        """
        mode: 'day' | 'week' | 'month'
        Retorna lista de {saleAmount, saleCount} por período.
        """
        # Período de resumen (siempre: hoy + mes actual como en la plataforma)
        now = datetime.now(TZ)
        fmt = "%Y-%m-%dT%H:%M:%S-06:00"
        today_s = datetime(now.year, now.month, now.day, 0,  0,  0, tzinfo=TZ).strftime(fmt)
        today_e = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=TZ).strftime(fmt)
        month_s = datetime(now.year, now.month, 1,       0,  0,  0, tzinfo=TZ).strftime(fmt)

        # Para el resumen de cards siempre mandamos hoy + mes
        summary_periods = [
            {"startTime": today_s, "endTime": today_e},
            {"startTime": month_s, "endTime": today_e},
        ]
        summary = self.req("POST", "/api/statistics/getSaleCount",
                           {"timePeriodList": summary_periods, "groupIds": "", "machineIds": ""})

        # Para la gráfica, períodos según el modo seleccionado
        chart_periods = self._periods(mode)
        chart = self.req("POST", "/api/statistics/getSaleCount",
                         {"timePeriodList": chart_periods, "groupIds": "", "machineIds": ""})

        return summary, chart, chart_periods

    def get_machines(self):
        return self.req("GET", "/api/terminal?sort=createDate%2Cdesc&page=0&size=100")

    def get_orders(self, size=200):
        return self.req("GET", f"/api/commodityOrder?page=0&size={size}&sort=createDate%2Cdesc")

    def get_products(self):
        return self.req("GET", "/api/goods?page=0&size=200")

    def get_replenishment(self):
        return self.req("GET", "/api/replenishmentOperations?page=0&size=100&sort=createDate%2Cdesc")

    def get_machine_status(self, code):
        return self.req("GET", f"/api/devCompStatus?terminalCode={code}&page=0&size=50")

    def send_command(self, code, ctrl):
        return self.req("POST", "/api/devCommand", {"terminalCode": code, "control": ctrl})


# ══════════════════════════════════════════════════════════
#  WIDGETS PERSONALIZADOS
# ══════════════════════════════════════════════════════════
class ModernFrame(tk.Frame):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["s1"])
        kw.setdefault("relief", "flat")
        super().__init__(parent, **kw)

class Title(tk.Label):
    def __init__(self, parent, text, size=13, color=None, **kw):
        kw["bg"]   = kw.get("bg", parent.cget("bg"))
        kw["fg"]   = color or C["bright"]
        kw["font"] = ("Segoe UI Semibold", size)
        kw["text"] = text
        super().__init__(parent, **kw)

class Subtitle(tk.Label):
    def __init__(self, parent, text, **kw):
        kw["bg"]   = kw.get("bg", parent.cget("bg"))
        kw["fg"]   = C["muted"]
        kw["font"] = ("Segoe UI", 9)
        kw["text"] = text
        super().__init__(parent, **kw)

class AccentButton(tk.Button):
    def __init__(self, parent, text, command=None, color=None, **kw):
        bg = color or C["accent"]
        kw.update(dict(text=text, command=command or (lambda: None),
                       bg=bg, fg="#000" if bg in (C["accent"], C["yellow"], C["green"]) else "#fff",
                       font=("Segoe UI Semibold", 10), relief="flat",
                       cursor="hand2", padx=14, pady=6, bd=0,
                       activebackground=bg, activeforeground="#000"))
        super().__init__(parent, **kw)
        self.bind("<Enter>", lambda e: self.config(bg=self._lighten(bg)))
        self.bind("<Leave>", lambda e: self.config(bg=bg))

    @staticmethod
    def _lighten(hex_color):
        h = hex_color.lstrip("#")
        r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        r = min(255, r + 25); g = min(255, g + 25); b = min(255, b + 25)
        return f"#{r:02x}{g:02x}{b:02x}"

class GhostButton(tk.Button):
    def __init__(self, parent, text, command=None, **kw):
        kw.update(dict(text=text, command=command or (lambda: None),
                       bg=C["s3"], fg=C["text"],
                       font=("Segoe UI", 9), relief="flat",
                       cursor="hand2", padx=10, pady=4, bd=0,
                       activebackground=C["border"], activeforeground=C["bright"]))
        super().__init__(parent, **kw)

class StatCard(tk.Frame):
    def __init__(self, parent, label, icon, color=None):
        super().__init__(parent, bg=C["s1"], padx=16, pady=14)
        self._color = color or C["accent"]
        self.val_var = tk.StringVar(value="—")
        self.sub_var = tk.StringVar(value="")

        top = tk.Frame(self, bg=C["s1"])
        top.pack(fill="x")
        tk.Label(top, text=icon, bg=C["s1"], fg=self._color,
                 font=("Segoe UI", 18)).pack(side="left")
        tk.Label(top, textvariable=self.val_var, bg=C["s1"], fg=C["bright"],
                 font=("Consolas", 24, "bold")).pack(side="left", padx=(10,0))

        tk.Label(self, text=label.upper(), bg=C["s1"], fg=C["muted"],
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(6,0))
        tk.Label(self, textvariable=self.sub_var, bg=C["s1"], fg=self._color,
                 font=("Segoe UI", 9)).pack(anchor="w")

    def set(self, val, sub=""):
        self.val_var.set(val)
        self.sub_var.set(sub)

class MiniBar(tk.Canvas):
    """Mini gráfica de barras verticales."""
    def __init__(self, parent, width=400, height=120, **kw):
        kw.update(bg=C["s1"], highlightthickness=0)
        super().__init__(parent, width=width, height=height, **kw)
        self._data   = []
        self._labels = []
        self._color  = C["accent"]

    def set_data(self, values, labels, color=None):
        self._data   = values
        self._labels = labels
        self._color  = color or C["accent"]
        self.after(10, self._draw)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width() or 400, self.winfo_height() or 120
        n    = len(self._data)
        if n == 0: return
        pad_b = 30
        pad_t = 8
        usable_h = h - pad_b - pad_t
        max_v = max(self._data) if max(self._data) > 0 else 1
        bar_w = max(4, (w - 20) // n - 4)

        for i, v in enumerate(self._data):
            x0 = 10 + i * ((w - 20) // n)
            bh = int((v / max_v) * usable_h)
            x1 = x0 + bar_w
            y0 = h - pad_b - bh
            y1 = h - pad_b

            # Barra
            alpha_color = self._color
            self.create_rectangle(x0, y0, x1, y1, fill=alpha_color, outline="", tags="bar")

            # Valor encima
            if v > 0:
                val_str = f"${int(v)}" if v >= 1 else str(int(v))
                self.create_text(x0 + bar_w//2, y0 - 4, text=val_str,
                                 fill=C["bright"], font=("Segoe UI", 7), anchor="s")

            # Etiqueta abajo
            if i < len(self._labels):
                lbl = self._labels[i]
                self.create_text(x0 + bar_w//2, h - pad_b + 6, text=lbl,
                                 fill=C["muted"], font=("Segoe UI", 7), anchor="n")

        # Línea base
        self.create_line(10, h - pad_b, w - 10, h - pad_b, fill=C["border"])

class ModernTree(ttk.Treeview):
    """Treeview con estilo oscuro."""
    _styled = False

    def __init__(self, parent, columns, col_widths=None, **kw):
        if not ModernTree._styled:
            s = ttk.Style()
            s.theme_use("default")
            s.configure("Dark.Treeview",
                        background=C["s1"], foreground=C["text"],
                        fieldbackground=C["s1"], rowheight=30,
                        font=("Segoe UI", 10), borderwidth=0)
            s.configure("Dark.Treeview.Heading",
                        background=C["s2"], foreground=C["muted"],
                        font=("Segoe UI", 9, "bold"), relief="flat")
            s.map("Dark.Treeview",
                  background=[("selected", C["s3"])],
                  foreground=[("selected", C["bright"])])
            ModernTree._styled = True

        super().__init__(parent, columns=columns, show="headings",
                         style="Dark.Treeview", **kw)
        for i, col in enumerate(columns):
            w = (col_widths or {}).get(col, 120)
            self.heading(col, text=col)
            self.column(col, width=w, minwidth=60)

        self.tag_configure("online",    foreground=C["accent"])
        self.tag_configure("offline",   foreground=C["red"])
        self.tag_configure("delivered", foreground=C["green"])
        self.tag_configure("pending",   foreground=C["yellow"])
        self.tag_configure("fail",      foreground=C["red"])
        self.tag_configure("active",    foreground=C["accent"])
        self.tag_configure("inactive",  foreground=C["muted"])
        self.tag_configure("alt",       background=C["s2"])

    def clear(self):
        self.delete(*self.get_children())

    def add_row(self, values, tags=()):
        idx = len(self.get_children())
        all_tags = list(tags) + (["alt"] if idx % 2 == 1 else [])
        self.insert("", "end", values=values, tags=all_tags)


# ══════════════════════════════════════════════════════════
#  APP PRINCIPAL
# ══════════════════════════════════════════════════════════
class VMCDesktop:
    def __init__(self, root):
        self.root    = root
        self.client  = API_Client()
        self.sel_mach= None
        self.machines= []
        self.orders  = []
        self.products= []
        self.rep     = []
        self.stats_mode = tk.StringVar(value="day")
        self.chart_data = []
        self.chart_lbls = []
        self.auto_refresh = True

        self._setup_window()
        self._build()
        self._start_auto_refresh()
        # Log inicial para confirmar que la app esta corriendo
        self._log("App iniciada correctamente", "ok")
        token = self.client._get_token()
        if token:
            self._log(f"Token cargado ({len(token)} chars)", "ok")
        else:
            self._log("Sin token — abre el dialogo de conexion", "er")
        # Lanzar carga en hilo
        self.root.after(500, lambda: threading.Thread(target=self._load_all, daemon=True).start())

    # ── VENTANA ─────────────────────────────────────────
    def _setup_window(self):
        self.root.title("VMC Control Center")
        self.root.geometry("1200x750")
        self.root.minsize(1000, 650)
        self.root.configure(bg=C["bg"])

    # ── BUILD ───────────────────────────────────────────
    def _build(self):
        # ── TOP BAR
        bar = tk.Frame(self.root, bg=C["s1"], height=52)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        tk.Label(bar, text="VMC", bg=C["s1"], fg=C["accent"],
                 font=("Consolas", 16, "bold")).pack(side="left", padx=(18,0))
        tk.Label(bar, text="·Control", bg=C["s1"], fg=C["bright"],
                 font=("Consolas", 16, "bold")).pack(side="left")
        tk.Label(bar, text="  v2", bg=C["s1"], fg=C["muted"],
                 font=("Consolas", 10)).pack(side="left")

        self._conn_lbl = tk.Label(bar, text="● Conectando...", bg=C["s1"], fg=C["muted"],
                                  font=("Segoe UI", 10))
        self._conn_lbl.pack(side="right", padx=18)

        self._upd_lbl = tk.Label(bar, text="", bg=C["s1"], fg=C["muted"],
                                 font=("Segoe UI", 9))
        self._upd_lbl.pack(side="right", padx=4)

        GhostButton(bar, "⟳  Actualizar",
                    command=lambda: threading.Thread(target=self._load_all, daemon=True).start()
                    ).pack(side="right", padx=6, pady=10)

        # ── NOTEBOOK
        nb_style = ttk.Style()
        nb_style.configure("V.TNotebook", background=C["bg"], borderwidth=0, tabmargins=0)
        nb_style.configure("V.TNotebook.Tab", background=C["s2"], foreground=C["muted"],
                            font=("Segoe UI", 10), padding=[16, 9])
        nb_style.map("V.TNotebook.Tab",
                     background=[("selected", C["bg"])],
                     foreground=[("selected", C["accent"])])

        self.nb = ttk.Notebook(self.root, style="V.TNotebook")
        self.nb.pack(fill="both", expand=True)

        self._t_dash  = tk.Frame(self.nb, bg=C["bg"])
        self._t_mach  = tk.Frame(self.nb, bg=C["bg"])
        self._t_ctrl  = tk.Frame(self.nb, bg=C["bg"])
        self._t_ord   = tk.Frame(self.nb, bg=C["bg"])
        self._t_items = tk.Frame(self.nb, bg=C["bg"])
        self._t_prod  = tk.Frame(self.nb, bg=C["bg"])
        self._t_rep   = tk.Frame(self.nb, bg=C["bg"])
        self._t_log   = tk.Frame(self.nb, bg=C["bg"])

        self.nb.add(self._t_dash,  text="📊  Dashboard")
        self.nb.add(self._t_mach,  text="🏪  Máquinas")
        self.nb.add(self._t_ctrl,  text="🎮  Control")
        self.nb.add(self._t_ord,   text="🧾  Pedidos")
        self.nb.add(self._t_items, text="📦  Artículos vendidos")
        self.nb.add(self._t_prod,  text="🗂️  Catálogo")
        self.nb.add(self._t_rep,   text="🔄  Reabastecimiento")
        self.nb.add(self._t_log,   text="📋  Log")

        self._build_dashboard()
        self._build_machines()
        self._build_control()
        self._build_orders()
        self._build_items()
        self._build_products()
        self._build_replenishment()
        self._build_log()

    # ── DASHBOARD ───────────────────────────────────────
    def _build_dashboard(self):
        f = self._t_dash
        pad = dict(padx=16, pady=8)

        # Stat cards
        cards_f = tk.Frame(f, bg=C["bg"])
        cards_f.pack(fill="x", **pad)
        self._sc = {
            "rev_day":    StatCard(cards_f, "Ingresos hoy",    "💰", C["accent"]),
            "cnt_day":    StatCard(cards_f, "Ventas hoy",      "🛒", C["blue"]),
            "cnt_month":  StatCard(cards_f, "Ventas mes",      "📅", C["purple"]),
            "rev_month":  StatCard(cards_f, "Monto mes",       "💵", C["yellow"]),
            "online":     StatCard(cards_f, "Máquinas online", "🏪", C["green"]),
        }
        for i, (_, card) in enumerate(self._sc.items()):
            card.grid(row=0, column=i, padx=5, pady=2, sticky="nsew")
            cards_f.columnconfigure(i, weight=1)

        # Selector de período + gráfica
        chart_f = tk.Frame(f, bg=C["s1"])
        chart_f.pack(fill="x", padx=16, pady=(4,8))

        hdr = tk.Frame(chart_f, bg=C["s1"])
        hdr.pack(fill="x", padx=14, pady=(12,6))
        Title(hdr, "Ventas por período", bg=C["s1"]).pack(side="left")

        # Radio buttons de período
        btn_f = tk.Frame(hdr, bg=C["s1"])
        btn_f.pack(side="right")
        for label, val in [("Hoy", "day"), ("7 días", "week"), ("Mes", "month")]:
            rb = tk.Radiobutton(btn_f, text=label, variable=self.stats_mode, value=val,
                                bg=C["s1"], fg=C["text"], selectcolor=C["s3"],
                                activebackground=C["s1"], activeforeground=C["accent"],
                                font=("Segoe UI", 10), cursor="hand2",
                                command=self._on_period_change)
            rb.pack(side="left", padx=6)

        self._mini_bar = MiniBar(chart_f, height=140)
        self._mini_bar.pack(fill="x", padx=14, pady=(0,12))

        # Últimas ventas
        ord_f = tk.Frame(f, bg=C["bg"])
        ord_f.pack(fill="both", expand=True, padx=16, pady=(0,12))

        hdr2 = tk.Frame(ord_f, bg=C["bg"])
        hdr2.pack(fill="x", pady=(0,6))
        Title(hdr2, "Últimas ventas", bg=C["bg"]).pack(side="left")
        self._dash_count = tk.Label(hdr2, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._dash_count.pack(side="left", padx=8)

        cols = ("Folio", "Producto", "Categoría", "Máquina", "Monto", "Fecha", "Estado")
        widths = {"Folio":155, "Producto":200, "Categoría":140, "Máquina":130,
                  "Monto":80, "Fecha":140, "Estado":90}
        self._dash_tree = ModernTree(ord_f, cols, widths)
        vsb = ttk.Scrollbar(ord_f, orient="vertical", command=self._dash_tree.yview)
        self._dash_tree.configure(yscrollcommand=vsb.set)
        self._dash_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _on_period_change(self):
        threading.Thread(target=self._load_stats, daemon=True).start()

    # ── MÁQUINAS ────────────────────────────────────────
    def _build_machines(self):
        f = self._t_mach
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Equipos registrados", bg=C["bg"]).pack(side="left")
        self._mach_count = tk.Label(tb, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._mach_count.pack(side="left", padx=10)
        GhostButton(tb, "⟳  Actualizar",
                    command=lambda: threading.Thread(target=self._load_machines,daemon=True).start()
                    ).pack(side="right")

        cols = ("Código/SN", "Nombre", "Estado", "Run Mode",
                "IP Interna", "IP Externa", "Versión SW", "Modelo", "Última sync")
        widths = {"Código/SN":130,"Nombre":140,"Estado":90,"Run Mode":80,
                  "IP Interna":120,"IP Externa":130,"Versión SW":90,"Modelo":150,"Última sync":140}
        self._mach_tree = ModernTree(f, cols, widths)
        vsb = ttk.Scrollbar(f, orient="vertical", command=self._mach_tree.yview)
        self._mach_tree.configure(yscrollcommand=vsb.set)

        frame = tk.Frame(f, bg=C["bg"])
        frame.pack(fill="both", expand=True, padx=16, pady=(0,12))
        self._mach_tree = ModernTree(frame, cols, widths)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._mach_tree.yview)
        self._mach_tree.configure(yscrollcommand=vsb.set)
        self._mach_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._mach_tree.bind("<<TreeviewSelect>>", self._on_mach_select)
        self._mach_tree.bind("<Double-1>", lambda e: self.nb.select(self._t_ctrl))

        tk.Label(f, text="↑ Doble clic para ir al panel de Control",
                 bg=C["bg"], fg=C["muted"], font=("Segoe UI",9)).pack(pady=(0,8))

    # ── CONTROL ─────────────────────────────────────────
    def _build_control(self):
        f = self._t_ctrl

        # Barra de info de máquina seleccionada
        info = tk.Frame(f, bg=C["s1"])
        info.pack(fill="x", padx=16, pady=(12,6))

        self._ctrl_icon = tk.Label(info, text="🏪", bg=C["s1"], font=("Segoe UI",22))
        self._ctrl_icon.pack(side="left", padx=(14,10), pady=10)

        name_f = tk.Frame(info, bg=C["s1"])
        name_f.pack(side="left", pady=10)
        self._ctrl_name = tk.StringVar(value="Selecciona una máquina en la pestaña 'Máquinas'")
        self._ctrl_meta = tk.StringVar(value="")
        tk.Label(name_f, textvariable=self._ctrl_name, bg=C["s1"], fg=C["bright"],
                 font=("Segoe UI Semibold",13)).pack(anchor="w")
        tk.Label(name_f, textvariable=self._ctrl_meta, bg=C["s1"], fg=C["muted"],
                 font=("Segoe UI",10)).pack(anchor="w")

        self._ctrl_status = tk.Label(info, text="", bg=C["s1"], font=("Segoe UI Semibold",11))
        self._ctrl_status.pack(side="right", padx=14)

        # Grilla de IPs
        grid_f = tk.Frame(f, bg=C["s2"])
        grid_f.pack(fill="x", padx=16, pady=4)
        self._ctrl_vars = {}
        for i, (key, lbl) in enumerate([("ip1","IP Interna"),("ip2","IP Externa"),
                                          ("ver","Versión SW"),("sync","Última sync")]):
            col = tk.Frame(grid_f, bg=C["s2"])
            col.grid(row=0, column=i, padx=16, pady=10, sticky="w")
            grid_f.columnconfigure(i, weight=1)
            tk.Label(col, text=lbl.upper(), bg=C["s2"], fg=C["muted"],
                     font=("Segoe UI",8)).pack(anchor="w")
            var = tk.StringVar(value="—")
            self._ctrl_vars[key] = var
            tk.Label(col, textvariable=var, bg=C["s2"], fg=C["bright"],
                     font=("Consolas",11,"bold")).pack(anchor="w")

        # Layout principal
        main = tk.Frame(f, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=8)

        left = tk.Frame(main, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, bg=C["s1"], width=280)
        right.pack(side="right", fill="y", padx=(12,0))
        right.pack_propagate(False)

        # Botones de comandos
        sections = [
            ("🔄  Control de servicio", [("0100","Normal Service"),("0101","Out of Service")]),
            ("⚙️  Sistema",             [("0302","Reboot"),("0301","Shutdown"),("0307","Restart SW"),("0401","Upgrade")]),
        ]
        for sec_title, cmds in sections:
            tk.Label(left, text=sec_title, bg=C["bg"], fg=C["muted"],
                     font=("Segoe UI Semibold",9)).pack(anchor="w", pady=(10,4))
            btn_row = tk.Frame(left, bg=C["bg"])
            btn_row.pack(fill="x", pady=(0,4))
            for ctrl, label in cmds:
                _, icon, dangerous, color = CMDS[ctrl]
                fg = "#000" if color in (C["green"],C["yellow"],C["accent"]) else "#fff"
                btn = tk.Button(btn_row, text=f"{icon}  {label}",
                                bg=C["s2"], fg=color,
                                font=("Segoe UI",10), relief="flat",
                                cursor="hand2", padx=12, pady=9, bd=0,
                                activebackground=C["s3"], activeforeground=color,
                                command=lambda c=ctrl,l=label,d=dangerous: self._send_cmd(c,l,d))
                btn.pack(side="left", fill="x", expand=True, padx=3)

        # Panel de estado
        tk.Label(right, text="📡  ESTADO", bg=C["s1"], fg=C["muted"],
                 font=("Segoe UI Semibold",9)).pack(anchor="w", padx=12, pady=(12,4))
        GhostButton(right, "⟳  Actualizar estado",
                    command=lambda: threading.Thread(target=self._load_mach_status,daemon=True).start()
                    ).pack(fill="x", padx=12, pady=(0,8))
        self._status_txt = scrolledtext.ScrolledText(
            right, bg=C["s2"], fg=C["text"], font=("Consolas",9),
            relief="flat", height=18, state="disabled", padx=8, pady=6)
        self._status_txt.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self._status_txt.tag_configure("ok",  foreground=C["accent"])
        self._status_txt.tag_configure("err", foreground=C["red"])
        self._status_txt.tag_configure("key", foreground=C["muted"])

    # ── PEDIDOS ─────────────────────────────────────────
    def _build_orders(self):
        f = self._t_ord
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Historial de pedidos", bg=C["bg"]).pack(side="left")
        self._ord_count = tk.Label(tb, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._ord_count.pack(side="left", padx=10)
        GhostButton(tb, "⟳",
                    command=lambda: threading.Thread(target=self._load_orders,daemon=True).start()
                    ).pack(side="right")

        cols   = ("Folio","Producto","Categoría","Máquina","Monto","Cant.","Fecha","Estado")
        widths = {"Folio":155,"Producto":200,"Categoría":140,"Máquina":130,
                  "Monto":80,"Cant.":50,"Fecha":140,"Estado":90}
        frame  = tk.Frame(f, bg=C["bg"])
        frame.pack(fill="both", expand=True, padx=16, pady=(0,12))
        self._ord_tree = ModernTree(frame, cols, widths)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._ord_tree.yview)
        self._ord_tree.configure(yscrollcommand=vsb.set)
        self._ord_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ── ARTÍCULOS VENDIDOS ──────────────────────────────
    def _build_items(self):
        f = self._t_items

        # Toolbar con filtros
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Artículos vendidos", bg=C["bg"]).pack(side="left")

        # Filtro de período
        filter_f = tk.Frame(tb, bg=C["bg"])
        filter_f.pack(side="right")
        self._items_mode = tk.StringVar(value="all")
        tk.Label(filter_f, text="Período:", bg=C["bg"], fg=C["muted"],
                 font=("Segoe UI",9)).pack(side="left", padx=(0,6))
        for label, val in [("Todo","all"),("Hoy","today"),("Semana","week"),("Mes","month")]:
            rb = tk.Radiobutton(filter_f, text=label, variable=self._items_mode, value=val,
                                bg=C["bg"], fg=C["text"], selectcolor=C["s2"],
                                activebackground=C["bg"], activeforeground=C["accent"],
                                font=("Segoe UI",10), cursor="hand2",
                                command=self._filter_items)
            rb.pack(side="left", padx=4)

        # Resumen por artículo
        sum_f = tk.Frame(f, bg=C["s1"])
        sum_f.pack(fill="x", padx=16, pady=(0,8))
        hdr = tk.Frame(sum_f, bg=C["s1"])
        hdr.pack(fill="x", padx=14, pady=(10,4))
        Title(hdr, "Resumen por artículo", bg=C["s1"], size=11).pack(side="left")
        self._items_count = tk.Label(hdr, text="", bg=C["s1"], fg=C["muted"], font=("Segoe UI",9))
        self._items_count.pack(side="left", padx=8)

        frame_sum = tk.Frame(sum_f, bg=C["s1"])
        frame_sum.pack(fill="x", padx=14, pady=(0,10))
        cols_sum   = ("Artículo","Categoría","Cant. vendida","Ingresos","% del total")
        widths_sum = {"Artículo":240,"Categoría":160,"Cant. vendida":100,"Ingresos":100,"% del total":90}
        self._items_sum_tree = ModernTree(frame_sum, cols_sum, widths_sum, height=8)
        vsb = ttk.Scrollbar(frame_sum, orient="vertical", command=self._items_sum_tree.yview)
        self._items_sum_tree.configure(yscrollcommand=vsb.set)
        self._items_sum_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Detalle de pedidos
        det_f = tk.Frame(f, bg=C["bg"])
        det_f.pack(fill="both", expand=True, padx=16, pady=(0,12))
        hdr2 = tk.Frame(det_f, bg=C["bg"])
        hdr2.pack(fill="x", pady=(0,6))
        Title(hdr2, "Detalle de pedidos", bg=C["bg"], size=11).pack(side="left")
        self._items_det_count = tk.Label(hdr2, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._items_det_count.pack(side="left", padx=8)

        cols_det   = ("Artículo","Categoría","Precio","Máquina","Fecha","Estado")
        widths_det = {"Artículo":220,"Categoría":160,"Precio":80,"Máquina":130,"Fecha":140,"Estado":90}
        frame_det  = tk.Frame(det_f, bg=C["bg"])
        frame_det.pack(fill="both", expand=True)
        self._items_det_tree = ModernTree(frame_det, cols_det, widths_det)
        vsb2 = ttk.Scrollbar(frame_det, orient="vertical", command=self._items_det_tree.yview)
        self._items_det_tree.configure(yscrollcommand=vsb2.set)
        self._items_det_tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")

    # ── CATÁLOGO ────────────────────────────────────────
    def _build_products(self):
        f = self._t_prod
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Catálogo de productos", bg=C["bg"]).pack(side="left")
        self._prod_count = tk.Label(tb, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._prod_count.pack(side="left", padx=10)
        GhostButton(tb, "⟳",
                    command=lambda: threading.Thread(target=self._load_products,daemon=True).start()
                    ).pack(side="right")
        cols   = ("ID","Nombre","Precio","Tipo/Categoría","Stock","Estado")
        widths = {"ID":80,"Nombre":220,"Precio":80,"Tipo/Categoría":160,"Stock":70,"Estado":80}
        frame  = tk.Frame(f, bg=C["bg"])
        frame.pack(fill="both", expand=True, padx=16, pady=(0,12))
        self._prod_tree = ModernTree(frame, cols, widths)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._prod_tree.yview)
        self._prod_tree.configure(yscrollcommand=vsb.set)
        self._prod_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ── REABASTECIMIENTO ────────────────────────────────
    def _build_replenishment(self):
        f = self._t_rep
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Registro de reabastecimiento", bg=C["bg"]).pack(side="left")
        self._rep_count = tk.Label(tb, text="", bg=C["bg"], fg=C["muted"], font=("Segoe UI",9))
        self._rep_count.pack(side="left", padx=10)
        GhostButton(tb, "⟳",
                    command=lambda: threading.Thread(target=self._load_rep,daemon=True).start()
                    ).pack(side="right")
        cols   = ("Fecha","Máquina","Artículo","Cantidad","Operador")
        widths = {"Fecha":140,"Máquina":130,"Artículo":220,"Cantidad":80,"Operador":140}
        frame  = tk.Frame(f, bg=C["bg"])
        frame.pack(fill="both", expand=True, padx=16, pady=(0,12))
        self._rep_tree = ModernTree(frame, cols, widths)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._rep_tree.yview)
        self._rep_tree.configure(yscrollcommand=vsb.set)
        self._rep_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ── LOG ─────────────────────────────────────────────
    def _build_log(self):
        f = self._t_log
        tb = tk.Frame(f, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=10)
        Title(tb, "Registro de actividad", bg=C["bg"]).pack(side="left")
        GhostButton(tb, "🗑  Limpiar",
                    command=lambda: (self._log_txt.config(state="normal"),
                                    self._log_txt.delete("1.0","end"),
                                    self._log_txt.config(state="disabled"))
                    ).pack(side="right")
        self._log_txt = scrolledtext.ScrolledText(
            f, bg=C["s1"], fg=C["text"], font=("Consolas",10),
            relief="flat", state="disabled", padx=12, pady=8)
        self._log_txt.pack(fill="both", expand=True, padx=16, pady=(0,12))
        for tag, color in [("ok",C["accent"]),("er",C["red"]),("in",C["blue"]),
                           ("wr",C["orange"]),("ts",C["purple"])]:
            self._log_txt.tag_configure(tag, foreground=color)

    # ══════════════════════════════════════════════════
    #  CARGA DE DATOS
    # ══════════════════════════════════════════════════
    def _load_all(self):
        self._log("Iniciando carga completa...", "in")
        # Verificar token con un endpoint simple (terminal)
        test = self.client.req("GET", "/api/terminal?page=0&size=1")
        if isinstance(test, dict) and test.get("error") == "TOKEN_EXPIRED":
            self._log("⚠ Token expirado — necesitas obtener uno nuevo", "er")
            self._set_conn(False)
            self.root.after(0, self._show_token_expired_dialog)
            return
        if isinstance(test, dict) and "error" in test:
            self._log(f"Error de conexion: {test.get('error')}", "er")
            self._set_conn(False)
            return
        # Conexion OK
        self._set_conn(True)
        # Lanzar cada loader en su propio hilo, con manejo de errores
        def safe_run(name, fn):
            try:
                fn()
            except Exception as e:
                self._log(f"Error en {name}: {e}", "er")
        threads = [
            threading.Thread(target=safe_run, args=("stats",   self._load_stats),    daemon=True),
            threading.Thread(target=safe_run, args=("machines",self._load_machines), daemon=True),
            threading.Thread(target=safe_run, args=("orders",  self._load_orders),   daemon=True),
            threading.Thread(target=safe_run, args=("products",self._load_products), daemon=True),
            threading.Thread(target=safe_run, args=("rep",     self._load_rep),      daemon=True),
        ]
        for t in threads: t.start()
        self.root.after(0, lambda: self._upd_lbl.config(
            text="Ultima sync: " + datetime.now().strftime("%H:%M:%S")))

    def _show_token_expired_dialog(self):
        if messagebox.askyesno(
            "Token expirado",
            "El token de acceso expiró.\n\n"
            "¿Quieres abrir la ventana para ingresar uno nuevo?"):
            # Crear ventana de re-login
            top = tk.Toplevel(self.root)
            dlg = LoginDialog(top)
            top.transient(self.root)
            top.grab_set()
            top.wait_window()
            if dlg.result:
                self._log("✓ Nuevo token configurado", "ok")
                threading.Thread(target=self._load_all, daemon=True).start()

    def _load_stats(self):
        mode = self.stats_mode.get()
        summary, chart, periods = self.client.get_stats(mode)
        self.root.after(0, lambda: self._apply_stats(summary, chart, periods, mode))

    def _apply_stats(self, summary, chart, periods, mode):
        # Cards de resumen (hoy y mes)
        if isinstance(summary, dict) and "data" in summary and isinstance(summary["data"], list):
            data   = summary["data"]
            today  = data[0] if len(data) > 0 else {}
            month  = data[1] if len(data) > 1 else {}
            rev_d  = int(float(today.get("saleAmount",0) or 0))
            cnt_d  = int(today.get("saleCount",0) or 0)
            rev_m  = int(float(month.get("saleAmount",0) or 0))
            cnt_m  = int(month.get("saleCount",0) or 0)
            self._sc["rev_day"].set(f"${rev_d:,}")
            self._sc["cnt_day"].set(str(cnt_d))
            self._sc["cnt_month"].set(str(cnt_m), f"${rev_m:,} MXN")
            self._sc["rev_month"].set(f"${rev_m:,}", f"{cnt_m} ventas")
            on = len([m for m in self.machines if m.get("status") in (True,1)])
            self._sc["online"].set(str(on) if self.machines else "—")
            self._set_conn(True)
            self._log(f"Stats OK: hoy={cnt_d} ventas ${rev_d} | mes={cnt_m} ventas ${rev_m:,} MXN", "ok")
        else:
            self._log(f"Stats: respuesta inesperada → {summary}", "wr")

        # Datos de gráfica
        if isinstance(chart, dict) and "data" in chart and isinstance(chart["data"], list):
            cdata = chart["data"]
            vals  = [float(d.get("saleAmount",0) or 0) for d in cdata]
            if mode == "day":
                lbls = ["Hoy"]
            elif mode == "week":
                lbls = [(datetime.now(TZ) - timedelta(days=6-i)).strftime("%d/%m")
                        for i in range(len(periods))]
            else:
                lbls = ["Mes actual"]
            self.chart_data = vals
            self.chart_lbls = lbls
            self._mini_bar.set_data(vals, lbls, C["accent"] if mode=="day" else
                                              (C["blue"] if mode=="week" else C["purple"]))

    def _load_machines(self):
        d = self.client.get_machines()
        if not d or "error" in d:
            self._log(f"Error máquinas: {d}", "er"); return
        lst = d.get("content") or d.get("list") or []
        self.machines = lst
        self.root.after(0, lambda: self._render_machines(lst))

    def _render_machines(self, lst):
        self._mach_tree.clear()
        on = 0
        for m in lst:
            ts  = m.get("terminalStatus") or {}
            is_on = m.get("status") in (True, 1)
            if is_on: on += 1
            tag = "online" if is_on else "offline"
            self._mach_tree.add_row((
                m.get("code","—"),
                m.get("name","—"),
                "● Online" if is_on else "● Offline",
                ts.get("runMode","—"),
                ts.get("intranetIp","—"),
                ts.get("internetIp","—"),
                ts.get("curVersion","—"),
                m.get("terminalModelCode","—"),
                (ts.get("lastUpdateTime","—") or "—")[:16],
            ), tags=(tag,))
        self._mach_count.config(text=f"{len(lst)} equipos · {on} online")
        self._sc["online"].set(str(on))
        self._log(f"{len(lst)} máquinas ({on} online)", "ok")

    def _on_mach_select(self, _event):
        sel = self._mach_tree.selection()
        if not sel: return
        vals = self._mach_tree.item(sel[0], "values")
        code = vals[0] if vals else ""
        m = next((x for x in self.machines if x.get("code") == code), None)
        if not m: return
        self.sel_mach = m
        ts  = m.get("terminalStatus") or {}
        is_on = m.get("status") in (True,1)
        self._ctrl_name.set(m.get("name") or m.get("code") or "—")
        self._ctrl_meta.set(f"SN: {m.get('code','—')} · {m.get('terminalModelCode','—')}")
        self._ctrl_status.config(text="● Online" if is_on else "● Offline",
                                 fg=C["accent"] if is_on else C["red"])
        self._ctrl_vars["ip1"].set(ts.get("intranetIp","—"))
        self._ctrl_vars["ip2"].set(ts.get("internetIp","—"))
        self._ctrl_vars["ver"].set(ts.get("curVersion","—"))
        self._ctrl_vars["sync"].set((ts.get("lastUpdateTime","—") or "—")[:16])
        threading.Thread(target=self._load_mach_status, daemon=True).start()
        self._log(f"Máquina: {m.get('name') or code}", "in")

    def _load_mach_status(self):
        if not self.sel_mach: return
        code = self.sel_mach.get("code","")
        d = self.client.get_machine_status(code)
        lst = (d or {}).get("content") or (d or {}).get("list") or []
        self.root.after(0, lambda: self._render_status(lst))

    def _render_status(self, lst):
        self._status_txt.config(state="normal")
        self._status_txt.delete("1.0","end")
        m  = self.sel_mach or {}
        ts = m.get("terminalStatus") or {}
        if lst:
            for c in lst[:15]:
                ok  = c.get("status") in (1, True, "normal")
                nm  = c.get("compType") or c.get("name","—")
                self._status_txt.insert("end", f"  {nm:<26}", "key")
                self._status_txt.insert("end", ("✓ OK\n" if ok else "✗ Error\n"),
                                        ("ok" if ok else "err"))
        else:
            for k, v in [("Estado",    "Online" if m.get("status") in (True,1) else "Offline"),
                          ("IP Interna",ts.get("intranetIp","—")),
                          ("IP Externa",ts.get("internetIp","—")),
                          ("Versión SW",ts.get("curVersion","—")),
                          ("RunMode",   ts.get("runMode","—")),
                          ("Sync",      (ts.get("lastUpdateTime","—") or "—")[:16])]:
                self._status_txt.insert("end", f"  {k:<16}", "key")
                self._status_txt.insert("end", f"{v}\n", "ok")
        self._status_txt.config(state="disabled")

    def _send_cmd(self, ctrl, label, dangerous):
        if not self.sel_mach:
            messagebox.showwarning("Sin selección", "Selecciona una máquina en la pestaña 'Máquinas'.")
            return
        if dangerous:
            nm = self.sel_mach.get("name") or self.sel_mach.get("code","")
            if not messagebox.askyesno("Confirmar acción",
                                       f"¿Ejecutar '{label}' en {nm}?\n\nEsta acción es inmediata."):
                return
        threading.Thread(target=self._exec_cmd, args=(ctrl, label), daemon=True).start()

    def _exec_cmd(self, ctrl, label):
        code = self.sel_mach.get("code","")
        self._log(f"→ devCommand {{terminalCode:{code}, control:{ctrl}}} [{label}]", "in")
        d = self.client.send_command(code, ctrl)
        if d and isinstance(d, dict) and "error" not in d:
            self._log(f"✓ {label} ejecutado correctamente en {code}", "ok")
            self.root.after(0, lambda: messagebox.showinfo("✅ Éxito", f"'{label}' ejecutado en {code}"))
        else:
            self._log(f"⚠ {label}: {d}", "wr")
            self.root.after(0, lambda: messagebox.showwarning("Enviado",
                             "Comando enviado (sin confirmación del servidor)"))

    def _load_orders(self):
        d = self.client.get_orders()
        if not d or "error" in d:
            self._log(f"Error pedidos: {d}", "er"); return
        lst = d.get("content") or d.get("list") or []
        self.orders = lst
        self.root.after(0, lambda: self._render_orders(lst))
        self.root.after(0, lambda: self._render_items())

    def _render_orders(self, lst):
        self._ord_tree.clear()
        self._dash_tree.clear()
        for i, o in enumerate(lst):
            det   = (o.get("commodityOrderDetailDtos") or [{}])[0]
            succ  = det.get("successNum",0) or 0
            fail  = det.get("failureNum", 0) or 0
            state = "Entregado" if succ > 0 else ("Fallo" if fail > 0 else "Pendiente")
            tag   = "delivered" if succ>0 else ("fail" if fail>0 else "pending")
            row = (
                (o.get("id","") or "")[:18],
                det.get("goodsName","—"),
                det.get("goodsTypeName","—"),
                o.get("terminalCode","—"),
                f"${float(o.get('totalAmount',0)):.2f}",
                det.get("orderNum","—"),
                (o.get("createDate","—") or "—")[:16],
                state,
            )
            self._ord_tree.add_row(row, tags=(tag,))
            if i < 10:
                self._dash_tree.add_row(row[:-1], tags=(tag,))  # sin Cant.

        self._ord_count.config(text=f"{len(lst)} pedidos")
        self._dash_count.config(text=f"{min(len(lst),10)} recientes")
        self._log(f"{len(lst)} pedidos cargados", "ok")

    def _filter_items(self):
        self.root.after(0, self._render_items)

    def _render_items(self):
        """Artículos vendidos con filtro de período y resumen agrupado."""
        now   = datetime.now(TZ)
        mode  = self._items_mode.get()
        items = []

        for o in self.orders:
            # Parsear fecha
            raw_date = o.get("createDate","") or ""
            try:
                dt = datetime.strptime(raw_date[:16], "%Y-%m-%d %H:%M")
            except:
                dt = None

            # Filtro de período
            if dt and mode != "all":
                if mode == "today":
                    if dt.date() != now.date(): continue
                elif mode == "week":
                    if (now.date() - dt.date()).days > 6: continue
                elif mode == "month":
                    if dt.year != now.year or dt.month != now.month: continue

            det = (o.get("commodityOrderDetailDtos") or [{}])[0]
            if not det.get("goodsName"): continue
            succ  = det.get("successNum",0) or 0
            fail  = det.get("failureNum", 0) or 0
            state = "Entregado" if succ>0 else ("Fallo" if fail>0 else "Pendiente")
            items.append({
                "name":     det.get("goodsName","—"),
                "category": det.get("goodsTypeName","—"),
                "amount":   float(o.get("totalAmount",0) or 0),
                "price":    float(det.get("singleAmount",0) or 0),
                "qty":      int(det.get("orderNum",1) or 1),
                "machine":  o.get("terminalCode","—"),
                "date":     (o.get("createDate","—") or "—")[:16],
                "state":    state,
            })

        # ── Resumen agrupado por artículo
        summary = {}
        total_rev = sum(i["amount"] for i in items)
        for item in items:
            k = item["name"]
            if k not in summary:
                summary[k] = {"name":k,"category":item["category"],"qty":0,"rev":0.0}
            summary[k]["qty"] += item["qty"]
            summary[k]["rev"] += item["amount"]

        self._items_sum_tree.clear()
        for s in sorted(summary.values(), key=lambda x: -x["rev"]):
            pct = f"{(s['rev']/total_rev*100):.1f}%" if total_rev > 0 else "—"
            self._items_sum_tree.add_row((
                s["name"], s["category"],
                str(s["qty"]), f"${s['rev']:.2f}", pct
            ))
        n_items = len(summary)
        self._items_count.config(text=f"{n_items} artículos · {len(items)} pedidos · ${total_rev:.2f} total")

        # ── Detalle
        self._items_det_tree.clear()
        for item in items:
            tag = "delivered" if item["state"]=="Entregado" else ("fail" if item["state"]=="Fallo" else "pending")
            self._items_det_tree.add_row((
                item["name"], item["category"],
                f"${item['price']:.2f}", item["machine"],
                item["date"], item["state"],
            ), tags=(tag,))
        self._items_det_count.config(text=f"{len(items)} pedidos en este período")

    def _load_products(self):
        d = self.client.get_products()
        if not d or "error" in d:
            self._log(f"Error productos: {d}", "er"); return
        lst = d.get("content") or d.get("list") or []
        self.products = lst
        self.root.after(0, lambda: self._render_products(lst))

    def _render_products(self, lst):
        self._prod_tree.clear()
        for p in lst:
            st  = "Activo" if p.get("status") in (True,1) else "Inactivo"
            tag = "active" if p.get("status") in (True,1) else "inactive"
            self._prod_tree.add_row((
                p.get("id","—"),
                p.get("name") or p.get("goodsName","—"),
                f"${p.get('price') or p.get('sellPrice',0)}",
                p.get("goodsTypeName") or p.get("typeName","—"),
                p.get("stock","—"),
                st,
            ), tags=(tag,))
        self._prod_count.config(text=f"{len(lst)} productos")
        self._log(f"{len(lst)} productos", "ok")

    def _load_rep(self):
        d = self.client.get_replenishment()
        # El endpoint puede dar 400 si no hay maquina seleccionada o sin parametros
        # No es critico - solo loguear y continuar
        if not d or (isinstance(d, dict) and ("error" in d or d.get("status") == 400)):
            self._log(f"Reabastecimiento no disponible: {d}", "wr")
            self.root.after(0, lambda: self._render_rep([]))
            return
        lst = d.get("content") or d.get("list") or []
        self.rep = lst
        self.root.after(0, lambda: self._render_rep(lst))

    def _render_rep(self, lst):
        self._rep_tree.clear()
        for r in lst:
            self._rep_tree.add_row((
                (r.get("createTime","—") or "—")[:16],
                r.get("terminalCode","—"),
                r.get("goodsName") or r.get("productName","—"),
                r.get("count") or r.get("quantity","—"),
                r.get("operName") or r.get("operator","—"),
            ))
        self._rep_count.config(text=f"{len(lst)} registros")
        self._log(f"{len(lst)} reabastecimientos", "ok")

    # ── LOG ─────────────────────────────────────────────
    def _log(self, msg, tag="in"):
        def _do():
            self._log_txt.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_txt.insert("end", f"[{ts}] ", "ts")
            self._log_txt.insert("end", msg + "\n", tag)
            self._log_txt.see("end")
            self._log_txt.config(state="disabled")
        self.root.after(0, _do)

    def _set_conn(self, ok):
        self._conn_lbl.config(
            text=("● En línea" if ok else "● Sin conexión"),
            fg=(C["accent"] if ok else C["red"]))

    # ── AUTO-REFRESH ────────────────────────────────────
    def _start_auto_refresh(self):
        def loop():
            while self.auto_refresh:
                time.sleep(60)
                if self.auto_refresh:
                    self._log("Auto-refresh...", "in")
                    threading.Thread(target=self._load_all, daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()


# ══════════════════════════════════════════════════════════
#  DIÁLOGO DE LOGIN
# ══════════════════════════════════════════════════════════
class LoginDialog:
    """Diálogo que pide al usuario pegar el token desde el navegador."""
    def __init__(self, root):
        self.root   = root
        self.result = None
        self._build()

    def _build(self):
        self.root.title("VMC Control Center — Conectar")
        self.root.geometry("560x600")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])
        try: self.root.eval("tk::PlaceWindow . center")
        except: pass

        # Logo
        tk.Label(self.root, text="VMC·Control", bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 22, "bold")).pack(pady=(28,4))
        tk.Label(self.root, text="Conexión a tu plataforma de máquinas",
                 bg=C["bg"], fg=C["muted"], font=("Segoe UI",10)).pack(pady=(0,16))

        # Card de instrucciones
        card = tk.Frame(self.root, bg=C["s1"], padx=22, pady=18)
        card.pack(fill="x", padx=24)

        tk.Label(card, text="Sigue estos 3 pasos para conectar:",
                 bg=C["s1"], fg=C["bright"], font=("Segoe UI Semibold",11)
                 ).pack(anchor="w", pady=(0,12))

        steps = [
            ("1", "Haz clic en \"Abrir navegador\" e inicia sesión normalmente",   C["blue"]),
            ("2", "Haz clic en \"Copiar token\" para extraerlo automáticamente",   C["accent"]),
            ("3", "Pega el token aquí abajo y haz clic en Conectar",                C["yellow"]),
        ]
        for num, txt, col in steps:
            row = tk.Frame(card, bg=C["s1"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=num, bg=col, fg="#000",
                     font=("Segoe UI Semibold",11), width=2,
                     ).pack(side="left", padx=(0,10))
            tk.Label(row, text=txt, bg=C["s1"], fg=C["text"],
                     font=("Segoe UI",10), wraplength=420, justify="left",
                     ).pack(side="left", anchor="w")

        # Botones de ayuda
        btn_row = tk.Frame(card, bg=C["s1"])
        btn_row.pack(fill="x", pady=(14,4))
        AccentButton(btn_row, "🌐  Abrir navegador",
                     command=self._open_browser, color=C["blue"]
                     ).pack(side="left", padx=(0,6), ipady=2)
        AccentButton(btn_row, "📋  Copiar token (script)",
                     command=self._copy_helper, color=C["yellow"]
                     ).pack(side="left", ipady=2)

        # Campo del token
        tk.Label(self.root, text="TOKEN JWT", bg=C["bg"], fg=C["muted"],
                 font=("Segoe UI",8)).pack(anchor="w", padx=24, pady=(18,4))
        self._token_entry = tk.Text(self.root, bg=C["s2"], fg=C["bright"],
                                    font=("Consolas",9), relief="flat",
                                    height=4, wrap="word",
                                    insertbackground=C["accent"])
        self._token_entry.pack(fill="x", padx=24, ipady=4)

        # Si ya hay token guardado, mostrarlo
        existing = load_token_from_file()
        if existing:
            self._token_entry.insert("1.0", existing)
            tk.Label(self.root, text="✓ Token cargado desde token.txt",
                     bg=C["bg"], fg=C["accent"], font=("Segoe UI",9)
                     ).pack(anchor="w", padx=24, pady=(4,0))

        # Botón conectar
        btn_frame = tk.Frame(self.root, bg=C["bg"])
        btn_frame.pack(fill="x", padx=24, pady=(18,4))
        self._btn = AccentButton(btn_frame, "  Conectar  ", command=self._connect)
        self._btn.pack(fill="x", ipady=6)

        # Estado
        self._status = tk.Label(self.root, text="", bg=C["bg"],
                                fg=C["red"], font=("Segoe UI",9), wraplength=500)
        self._status.pack(pady=(8,0))

        self._token_entry.focus()

    def _open_browser(self):
        webbrowser.open("https://a.vmc002.csmology.com")

    def _copy_helper(self):
        # Mostrar un script que el usuario puede pegar en la consola del navegador
        helper = tk.Toplevel(self.root)
        helper.title("Script para copiar el token")
        helper.geometry("600x420")
        helper.configure(bg=C["bg"])

        tk.Label(helper, text="Copia este script y pégalo en la consola del navegador (F12 → Console):",
                 bg=C["bg"], fg=C["text"], font=("Segoe UI",10),
                 wraplength=560).pack(padx=20, pady=(20,10), anchor="w")

        # Script que muestra el token directamente — el usuario lo copia con Ctrl+C
        script = ('copy(document.querySelector("#app").__vue__.$store.state.user.token)')

        txt = tk.Text(helper, bg=C["s2"], fg=C["accent"],
                      font=("Consolas",9), relief="flat",
                      height=6, wrap="word",
                      insertbackground=C["accent"])
        txt.pack(fill="x", padx=20, pady=4)
        txt.insert("1.0", script)
        txt.config(state="disabled")

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(script)
            self.root.update()
            cp_btn.config(text="✓  Copiado al portapapeles")

        cp_btn = AccentButton(helper, "📋  Copiar este script", command=copy_to_clipboard)
        cp_btn.pack(fill="x", padx=20, pady=10, ipady=4)

        info = ("1. Inicia sesión en a.vmc002.csmology.com\n"
                "2. Presiona F12 para abrir DevTools\n"
                "3. Ve a la pestaña 'Console'\n"
                "4. Pega el script de arriba y presiona Enter\n"
                "5. El token se copiará automáticamente al portapapeles\n"
                "6. Vuelve aquí y pégalo (Ctrl+V) en el campo TOKEN JWT")
        tk.Label(helper, text=info, bg=C["bg"], fg=C["muted"],
                 font=("Segoe UI",9), justify="left",
                 wraplength=560).pack(padx=20, pady=(4,10), anchor="w")

    def _connect(self):
        tok = self._token_entry.get("1.0", "end").strip()
        if not tok:
            self._status.config(text="Pega el token en el campo de arriba.", fg=C["red"])
            return
        # Formato del token: "Bearer eyJ..." o solo "eyJ..."
        if not tok.startswith("Bearer "):
            tok = "Bearer " + tok
        # Validar formato JWT (3 partes separadas por punto)
        jwt_part = tok[7:]  # quitar "Bearer "
        if jwt_part.count(".") != 2 or len(jwt_part) < 50:
            self._status.config(
                text="Token invalido. Debe ser un JWT valido.\n"
                     "Asegurate de copiarlo completo.",
                fg=C["red"])
            return

        # Guardar token directamente y entrar a la app
        # La app probara el token al cargar datos y mostrara error si esta expirado
        with _token_lock:
            _current_token["value"] = tok
        save_token_to_file(tok)
        self.result = True
        self.root.destroy()


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Pantalla de login
    login_root = tk.Tk()
    login_dlg  = LoginDialog(login_root)
    login_root.mainloop()

    if not login_dlg.result:
        exit(0)

    # App principal
    root = tk.Tk()
    app  = VMCDesktop(root)

    def on_close():
        app.auto_refresh = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
