#!/usr/bin/env python3
"""
VMC Control Center Desktop v4 — Servidor Local
Migración completa de csmology.com a servidor local (localhost:8080).

Cambios vs v3:
  - API: localhost:8080 en vez de api.vmc002.csmology.com
  - Sin token JWT requerido (red local)
  - WebSocket para datos en tiempo real
  - Navegación por fechas: día, semana, mes, año
  - Gráfica de barras con vista semanal (7 días) y mensual (12 meses)
  - Inventario con tracking automático de stock
  - Auto-refresh 30s + push via WebSocket
"""
import os, sys

# ═══════════════════════════════════════════════════════════════
#  HIGH DPI / RETINA SUPPORT
# ═══════════════════════════════════════════════════════════════
if sys.platform == "win32":
    try:
        from ctypes import windll
        try:    windll.shcore.SetProcessDpiAwareness(2)
        except:
            try:    windll.shcore.SetProcessDpiAwareness(1)
            except: windll.user32.SetProcessDPIAware()
    except: pass

def _get_dpi_scale():
    if sys.platform != "win32": return 1.0
    try:
        from ctypes import windll
        hdc = windll.user32.GetDC(0)
        dpi = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except: return 1.0

DPI_SCALE = _get_dpi_scale()

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading, json, time, math
from datetime import datetime, timezone, timedelta
from collections import Counter

# Dependencias externas
try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests")
    import requests

try:
    import websocket
except ImportError:
    os.system(f"{sys.executable} -m pip install websocket-client")
    import websocket

# ═══════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
SERVER_HOST = "localhost"
SERVER_PORT = 8080
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
WS_URL   = f"ws://{SERVER_HOST}:{SERVER_PORT}/ws/dashboard"
MACHINE_CODE = "BC8A08520A50"
TZ = timezone(timedelta(hours=-6))

try:
    if getattr(sys, 'frozen', False): SCRIPT_DIR = os.path.dirname(sys.executable)
    else: SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

# ═══════════════════════════════════════════════════════════════
#  PALETA — Mismo estilo BI claro que v3
# ═══════════════════════════════════════════════════════════════
C = {
    "bg":          "#f4f6fa",
    "card":        "#ffffff",
    "card_border": "#e2e8f0",
    "header":      "#ffffff",
    "sidebar":     "#1e2233",
    "sidebar_hov": "#2a3047",
    "sidebar_act": "#00a884",
    "text":        "#1f2937",
    "text_2":      "#4b5563",
    "muted":       "#9ca3af",
    "label":       "#6b7280",
    "green":       "#00c896",
    "green_2":     "#00a884",
    "green_lt":    "#dcfce7",
    "red":         "#ef4444",
    "red_lt":      "#fee2e2",
    "amber":       "#f59e0b",
    "amber_lt":    "#fef3c7",
    "blue":        "#3b82f6",
    "blue_lt":     "#dbeafe",
    "purple":      "#8b5cf6",
    "purple_lt":   "#ede9fe",
    "pink":        "#ec4899",
    "teal":        "#14b8a6",
    "bar_a":       "#10b981",
    "bar_b":       "#3b82f6",
    "bar_c":       "#f59e0b",
    "bar_d":       "#8b5cf6",
}

# ═══════════════════════════════════════════════════════════════
#  API CLIENT — Servidor local
# ═══════════════════════════════════════════════════════════════
class APIClient:
    def __init__(self, base=BASE_URL):
        self.base = base
        self.s = requests.Session()
        self.s.headers["Content-Type"] = "application/json"
        self.timeout = 10

    def _g(self, path, params=None):
        try:
            r = self.s.get(f"{self.base}{path}", params=params, timeout=self.timeout)
            r.raise_for_status(); return r.json()
        except Exception as e: return {"error": str(e)}

    def _p(self, path, data=None):
        try:
            r = self.s.post(f"{self.base}{path}", json=data or {}, timeout=self.timeout)
            r.raise_for_status(); return r.json()
        except Exception as e: return {"error": str(e)}

    def _put(self, path, data=None):
        try:
            r = self.s.put(f"{self.base}{path}", json=data or {}, timeout=self.timeout)
            r.raise_for_status(); return r.json()
        except Exception as e: return {"error": str(e)}

    def health(self):
        r = self._g("/api/health")
        return "error" not in r

    def get_summary(self):     return self._g("/api/sales/summary")
    def get_products(self):    return self._g("/api/products")
    def get_inventory(self):   return self._g("/api/inventory")
    def get_low_stock(self, t=3): return self._g("/api/inventory/low-stock", {"threshold": t})
    def get_machine_status(self): return self._g("/api/machine/status")
    def get_config(self):      return self._g("/api/config")
    def get_events(self, n=200): return self._g("/api/events", {"limit": n})
    def get_sales_by_product(self, f=None, t=None):
        p = {}
        if f: p["from"] = f
        if t: p["to"] = t
        return self._g("/api/sales/by-product", p)
    def get_sales_by_day(self, days=30): return self._g("/api/sales/by-day", {"days": days})

    def get_sales(self, from_d=None, to_d=None, status=None, limit=500):
        p = {"limit": limit}
        if from_d: p["from"] = from_d
        if to_d:   p["to"] = to_d
        if status: p["status"] = status
        return self._g("/api/sales", p)

    def send_command(self, cmd, params=None):
        return self._p("/api/machine/command", {"command": cmd, "params": params or {}})

    def refill(self, pid, slot, qty):
        return self._p("/api/inventory/refill", {"product_id": pid, "slot": slot, "quantity": qty})

    def update_product(self, pid, data):
        return self._put(f"/api/products/{pid}", data)

    def get_stats_periods(self, periods):
        """Formato compatible con csmology para las gráficas."""
        return self._p("/api/statistics/getSaleCount", {
            "timePeriodList": periods, "groupIds": "", "machineIds": ""
        })


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET
# ═══════════════════════════════════════════════════════════════
class WSClient:
    def __init__(self, url, on_msg=None):
        self.url, self.on_msg, self.ws, self.running = url, on_msg, None, False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.ws:
            try: self.ws.close()
            except: pass

    def _loop(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(self.url,
                    on_message=lambda ws,m: self._handle(m),
                    on_error=lambda ws,e: None,
                    on_close=lambda ws,c,m: None)
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except: pass
            if self.running: time.sleep(5)

    def _handle(self, msg):
        try:
            if self.on_msg: self.on_msg(json.loads(msg))
        except: pass


# ═══════════════════════════════════════════════════════════════
#  CANVAS GRÁFICAS — Idénticas a v3
# ═══════════════════════════════════════════════════════════════
class BarChart(tk.Canvas):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["card"]); kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._data, self._labels, self._color, self._unit = [], [], C["bar_a"], "$"
        self.bind("<Configure>", lambda e: self._draw())

    def set_data(self, values, labels, color=None, unit="$"):
        self._data = values or []; self._labels = labels or []
        self._color = color or C["bar_a"]; self._unit = unit
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width() or 600, self.winfo_height() or 280
        if not self._data:
            self.create_text(w/2, h/2, text="Sin datos", fill=C["muted"], font=("Segoe UI", 11))
            return
        ml, mr, mt, mb = 60, 30, 30, 50
        cw, ch = w-ml-mr, h-mt-mb
        mx = max(self._data) if max(self._data) > 0 else 1
        nm = self._nice(mx)
        for i in range(5):
            v = nm * (4-i) / 4; y = mt + ch * i / 4.0
            self.create_line(ml, y, w-mr, y, fill=C["card_border"])
            self.create_text(ml-10, y, text=f"{int(v):,}", fill=C["label"],
                             font=("Segoe UI", 9), anchor="e")
        zy = mt + ch
        self.create_line(ml, zy, w-mr, zy, fill=C["text_2"], width=2)
        n = len(self._data); bs = cw / n; bw = min(50, bs * 0.55)
        for i, v in enumerate(self._data):
            cx = ml + bs*(i+0.5); x0 = cx-bw/2; x1 = cx+bw/2
            bh = (v/nm)*ch if nm > 0 else 0; y0 = zy - bh
            self.create_rectangle(x0+2, y0+2, x1+2, zy, fill="#e2e8f0", outline="")
            self.create_rectangle(x0, y0, x1, zy, fill=self._color, outline="")
            self.create_rectangle(x0, y0, x1, y0+3, fill=self._lighten(self._color), outline="")
            if v > 0:
                self.create_text(cx, y0-8, text=f"{self._unit}{int(v):,}",
                                 fill=C["text"], font=("Segoe UI Semibold", 10), anchor="s")
            if i < len(self._labels):
                self.create_text(cx, zy+10, text=self._labels[i],
                                 fill=C["label"], font=("Segoe UI", 9), anchor="n")

    @staticmethod
    def _nice(v):
        if v <= 0: return 100
        mag = 10 ** int(math.log10(v))
        for m in [1,1.5,2,2.5,3,5,7.5,10]:
            if v <= m*mag: return m*mag
        return 10*mag

    @staticmethod
    def _lighten(hc, a=40):
        h = hc.lstrip("#")
        return f"#{min(255,int(h[0:2],16)+a):02x}{min(255,int(h[2:4],16)+a):02x}{min(255,int(h[4:6],16)+a):02x}"


class DonutChart(tk.Canvas):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["card"]); kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._data = []
        self.bind("<Configure>", lambda e: self._draw())

    def set_data(self, data):
        self._data = data or []; self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width() or 300, self.winfo_height() or 280
        if not self._data:
            self.create_text(w/2, h/2, text="Sin datos", fill=C["muted"], font=("Segoe UI", 11))
            return
        total = sum(v for _,v,_ in self._data) or 1
        cw = w * 0.55; cx, cy = cw/2, h/2
        ro = min(cw,h)/2-24; ri = ro*0.62
        start = 90
        for lbl, val, col in self._data:
            ext = -360*(val/total)
            self.create_arc(cx-ro,cy-ro,cx+ro,cy+ro, start=start, extent=ext,
                            fill=col, outline="white", width=3, style="pieslice")
            start += ext
        self.create_oval(cx-ri,cy-ri,cx+ri,cy+ri, fill=C["card"], outline="")
        self.create_text(cx, cy-12, text=f"{int(total)}", fill=C["text"],
                         font=("Segoe UI", 24, "bold"))
        self.create_text(cx, cy+16, text="TOTAL", fill=C["muted"],
                         font=("Segoe UI Semibold", 9))
        lx, ly, lh = cw+12, 28, 38
        for lbl, val, col in self._data:
            pct = val/total*100
            nm = lbl if len(lbl) <= 22 else lbl[:20]+"..."
            self.create_rectangle(lx, ly+2, lx+14, ly+14, fill=col, outline="")
            self.create_text(lx+22, ly+1, text=nm, fill=C["text"],
                             font=("Segoe UI Semibold", 10), anchor="nw")
            self.create_text(lx+22, ly+18, text=f"{int(val)} uds · {pct:.1f}%",
                             fill=C["muted"], font=("Segoe UI", 9), anchor="nw")
            ly += lh


# ═══════════════════════════════════════════════════════════════
#  WIDGETS — Idénticos a v3
# ═══════════════════════════════════════════════════════════════
class KPICard(tk.Frame):
    def __init__(self, parent, label, icon, color):
        super().__init__(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["card_border"])
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        hdr = tk.Frame(inner, bg=C["card"]); hdr.pack(fill="x")
        ib = tk.Frame(hdr, bg=C["card"], width=44, height=44)
        ib.pack(side="left"); ib.pack_propagate(False)
        cv = tk.Canvas(ib, width=44, height=44, bg=C["card"], highlightthickness=0); cv.pack()
        cv.create_oval(2,2,42,42, fill=self._tint(color), outline="")
        cv.create_text(22, 22, text=icon, font=("Segoe UI Emoji", 16))
        tk.Label(hdr, text=label.upper(), bg=C["card"], fg=C["label"],
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(10,0), pady=(8,0), anchor="nw")
        self.val_var = tk.StringVar(value="—")
        tk.Label(inner, textvariable=self.val_var, bg=C["card"], fg=C["text"],
                 font=("Segoe UI", 28, "bold")).pack(anchor="w", pady=(8,0))
        self.sub_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.sub_var, bg=C["card"], fg=color,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")

    @staticmethod
    def _tint(hc):
        h = hc.lstrip("#")
        r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return f"#{int(r*0.18+255*0.82):02x}{int(g*0.18+255*0.82):02x}{int(b*0.18+255*0.82):02x}"

    def set(self, val, sub=""):
        self.val_var.set(val); self.sub_var.set(sub)


class Card(tk.Frame):
    def __init__(self, parent, title=None, **kw):
        kw.setdefault("bg", C["card"]); kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", C["card_border"])
        super().__init__(parent, **kw)
        if title:
            self.head = tk.Frame(self, bg=C["card"]); self.head.pack(fill="x", padx=18, pady=(14,0))
            tk.Label(self.head, text=title, bg=C["card"], fg=C["text"],
                     font=("Segoe UI Semibold", 12)).pack(side="left")
        else:
            self.head = None
        self.body = tk.Frame(self, bg=C["card"])
        self.body.pack(fill="both", expand=True, padx=18, pady=(8,14))


class SoftButton(tk.Button):
    def __init__(self, parent, text, command=None, color=None, kind="solid", **kw):
        bg = color or C["green"]
        if kind == "solid":
            kw.update(dict(bg=bg, fg="white" if bg != C["amber"] else C["text"],
                           activebackground=bg, activeforeground="white"))
            self._hover = self._dk(bg)
        else:
            kw.update(dict(bg=C["card"], fg=bg, activebackground=C["card"], activeforeground=bg))
            self._hover = "#f3f4f6"
        kw.update(dict(text=text, command=command or (lambda:None),
                       font=("Segoe UI Semibold", 10), relief="flat",
                       cursor="hand2", padx=14, pady=7, bd=0))
        super().__init__(parent, **kw)
        self._nbg = self.cget("bg")
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._nbg))

    @staticmethod
    def _dk(hc):
        h = hc.lstrip("#")
        return f"#{max(0,int(h[0:2],16)-25):02x}{max(0,int(h[2:4],16)-25):02x}{max(0,int(h[4:6],16)-25):02x}"


class ModernTree(ttk.Treeview):
    _styled = False
    def __init__(self, parent, columns, col_widths=None, **kw):
        if not ModernTree._styled:
            s = ttk.Style(); s.theme_use("clam")
            s.configure("BI.Treeview", background=C["card"], foreground=C["text"],
                        fieldbackground=C["card"], rowheight=36,
                        font=("Segoe UI", 10), borderwidth=0, relief="flat")
            s.configure("BI.Treeview.Heading", background="#f9fafb", foreground=C["label"],
                        font=("Segoe UI Semibold", 9), relief="flat", padding=(10,10))
            s.map("BI.Treeview.Heading", background=[("active","#f3f4f6")])
            s.map("BI.Treeview", background=[("selected",C["green_lt"])],
                  foreground=[("selected",C["text"])])
            s.layout("BI.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            s.configure("Vertical.TScrollbar", background="#e5e7eb", troughcolor=C["card"],
                        borderwidth=0, arrowsize=14, relief="flat")
            ModernTree._styled = True
        super().__init__(parent, columns=columns, show="headings", style="BI.Treeview", **kw)
        for col in columns:
            w = (col_widths or {}).get(col, 120)
            self.heading(col, text=col); self.column(col, width=w, minwidth=60)
        self.tag_configure("delivered", foreground=C["green_2"], font=("Segoe UI Semibold", 10))
        self.tag_configure("pending",   foreground=C["amber"],   font=("Segoe UI Semibold", 10))
        self.tag_configure("fail",      foreground=C["red"],     font=("Segoe UI Semibold", 10))
        self.tag_configure("online",    foreground=C["green_2"], font=("Segoe UI Semibold", 10))
        self.tag_configure("offline",   foreground=C["red"],     font=("Segoe UI Semibold", 10))
        self.tag_configure("alt",       background="#fafbfc")
        self.tag_configure("low_stock", foreground=C["red"],     font=("Segoe UI Semibold", 10))

    def clear(self): self.delete(*self.get_children())
    def add_row(self, values, tags=()):
        idx = len(self.get_children())
        self.insert("", "end", values=values, tags=list(tags) + (["alt"] if idx%2 else []))


class Sidebar(tk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=C["sidebar"], width=72)
        self.pack_propagate(False)
        self._on_select, self._buttons, self._active = on_select, {}, None
        logo = tk.Frame(self, bg=C["sidebar"], height=72); logo.pack(fill="x"); logo.pack_propagate(False)
        tk.Label(logo, text="VMC", bg=C["sidebar"], fg=C["green"],
                 font=("Consolas", 16, "bold")).pack(pady=22)
        self.items_frame = tk.Frame(self, bg=C["sidebar"]); self.items_frame.pack(fill="both", expand=True)

    def add_item(self, key, icon, label):
        btn = tk.Frame(self.items_frame, bg=C["sidebar"], height=56, cursor="hand2")
        btn.pack(fill="x"); btn.pack_propagate(False)
        ind = tk.Frame(btn, bg=C["sidebar"], width=3); ind.pack(side="left", fill="y")
        ic = tk.Label(btn, text=icon, bg=C["sidebar"], fg="#7a8299", font=("Segoe UI Emoji", 18))
        ic.pack(expand=True)
        def enter(e):
            if self._active != key:
                for w in (btn,ic,ind): w.config(bg=C["sidebar_hov"])
        def leave(e):
            if self._active != key:
                for w in (btn,ic,ind): w.config(bg=C["sidebar"])
        def click(e): self.set_active(key); self._on_select(key)
        for w in (btn,ic,ind): w.bind("<Enter>",enter); w.bind("<Leave>",leave); w.bind("<Button-1>",click)
        self._buttons[key] = (btn, ic, ind, label)
        if not self._active: self.set_active(key)

    def set_active(self, key):
        for k,(b,i,d,_) in self._buttons.items():
            b.config(bg=C["sidebar"]); i.config(bg=C["sidebar"], fg="#7a8299"); d.config(bg=C["sidebar"])
        if key in self._buttons:
            b,i,d,_ = self._buttons[key]
            b.config(bg=C["sidebar_hov"]); i.config(bg=C["sidebar_hov"], fg=C["green"]); d.config(bg=C["green"])
        self._active = key


# ═══════════════════════════════════════════════════════════════
#  APP PRINCIPAL
# ═══════════════════════════════════════════════════════════════
class VMCDesktop:
    def __init__(self, root):
        self.root = root
        self.client = APIClient()
        self.ws = None
        self.machines, self.orders, self.products, self.sales = [], [], [], []
        self.stats_mode = tk.StringVar(value="week")
        self.auto_refresh = True
        self._current_tab = None
        self._tab_frames = {}

        # Fecha de navegación para gráficas
        self._nav_date = datetime.now(TZ)

        self._setup_window()
        self._build()
        self._show_tab("dash")
        self._start_ws()
        self._start_auto_refresh()
        self.root.after(300, lambda: threading.Thread(target=self._load_all, daemon=True).start())

    def _setup_window(self):
        self.root.title("VMC Control Center v4")
        w = int(1280 * max(1.0, DPI_SCALE * 0.85))
        h = int(800  * max(1.0, DPI_SCALE * 0.85))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(1100 * max(1.0, DPI_SCALE * 0.8)), int(700 * max(1.0, DPI_SCALE * 0.8)))
        self.root.configure(bg=C["bg"])
        try:
            from tkinter import font as tkfont
            tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI")
            tkfont.nametofont("TkTextFont").configure(family="Segoe UI")
        except: pass

    def _build(self):
        main = tk.Frame(self.root, bg=C["bg"]); main.pack(fill="both", expand=True)

        self.sidebar = Sidebar(main, on_select=self._show_tab)
        self.sidebar.pack(side="left", fill="y")

        content = tk.Frame(main, bg=C["bg"]); content.pack(side="left", fill="both", expand=True)

        # Top bar
        topbar = tk.Frame(content, bg=C["header"], height=56,
                          highlightthickness=1, highlightbackground=C["card_border"])
        topbar.pack(fill="x", side="top"); topbar.pack_propagate(False)

        tf = tk.Frame(topbar, bg=C["header"]); tf.pack(side="left", padx=20, pady=14)
        tk.Label(tf, text="VMC Control Center", bg=C["header"], fg=C["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        self._title_var = tk.StringVar(value="Dashboard")
        tk.Label(tf, textvariable=self._title_var, bg=C["header"], fg=C["text"],
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")

        right = tk.Frame(topbar, bg=C["header"]); right.pack(side="right", padx=20, pady=12)
        self._upd_lbl = tk.Label(right, text="", bg=C["header"], fg=C["muted"],
                                 font=("Segoe UI", 9))
        self._upd_lbl.pack(side="left", padx=(0,12))
        self._conn_canvas = tk.Canvas(right, width=110, height=28, bg=C["header"], highlightthickness=0)
        self._conn_canvas.pack(side="left", padx=8)
        self._draw_conn(False)
        SoftButton(right, "↻  Actualizar",
                   command=lambda: threading.Thread(target=self._load_all, daemon=True).start(),
                   color=C["green"]).pack(side="left", padx=4)

        self.body = tk.Frame(content, bg=C["bg"]); self.body.pack(fill="both", expand=True)

        self._build_dashboard()
        self._build_machines()
        self._build_control()
        self._build_orders()
        self._build_items()
        self._build_products()
        self._build_inventory()
        self._build_log()

        for key, icon, label in [
            ("dash","📊","Dashboard"), ("mach","🏪","Máquinas"), ("ctrl","🎮","Control"),
            ("ord","🧾","Pedidos"), ("items","📦","Ventas"), ("prod","🗂","Catálogo"),
            ("inv","📋","Inventario"), ("log","📝","Log"),
        ]:
            self.sidebar.add_item(key, icon, label)

    def _draw_conn(self, ok):
        c = self._conn_canvas; c.delete("all")
        bg = C["green_lt"] if ok else C["red_lt"]; fg = C["green_2"] if ok else C["red"]
        txt = "● Servidor local" if ok else "● Sin conexión"
        c.create_rectangle(0,4,110,24, fill=bg, outline="")
        c.create_text(55, 14, text=txt, fill=fg, font=("Segoe UI Semibold", 9))

    def _show_tab(self, key):
        for k, f in self._tab_frames.items(): f.pack_forget()
        if key in self._tab_frames: self._tab_frames[key].pack(fill="both", expand=True)
        self._current_tab = key
        titles = {"dash":"Dashboard", "mach":"Máquinas", "ctrl":"Panel de control",
                  "ord":"Historial de pedidos", "items":"Ventas reales · Artículos entregados",
                  "prod":"Catálogo de productos", "inv":"Inventario y stock", "log":"Registro de actividad"}
        self._title_var.set(titles.get(key, ""))
        if key == "items": self._render_items()
        if key == "inv":   self._refresh_inventory()

    def _make_scrollable(self, parent):
        cv = tk.Canvas(parent, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        inner = tk.Frame(cv, bg=C["bg"])
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cid = cv.create_window((0,0), window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfig(cid, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta/120), "units"))
        return inner

    # ──────────────────────────────────────────
    #  DASHBOARD
    # ──────────────────────────────────────────
    def _build_dashboard(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["dash"] = f
        scroll = self._make_scrollable(f)

        # KPI Cards
        kpi = tk.Frame(scroll, bg=C["bg"]); kpi.pack(fill="x", padx=24, pady=(20,12))
        self._kpi = {
            "rev_day":   KPICard(kpi, "Ingresos hoy",   "💰", C["green"]),
            "cnt_day":   KPICard(kpi, "Ventas hoy",     "🛒", C["blue"]),
            "cnt_month": KPICard(kpi, "Ventas del mes",  "📅", C["purple"]),
            "rev_month": KPICard(kpi, "Monto del mes",   "💵", C["amber"]),
            "online":    KPICard(kpi, "Servidor",        "🏪", C["teal"]),
        }
        for i, (_, card) in enumerate(self._kpi.items()):
            card.grid(row=0, column=i, padx=6, sticky="nsew", ipady=2)
            kpi.columnconfigure(i, weight=1)

        # Charts row
        chart_row = tk.Frame(scroll, bg=C["bg"]); chart_row.pack(fill="x", padx=24, pady=12)

        # Bar chart card
        bar_card = Card(chart_row, title="Ingresos por período")
        bar_card.pack(side="left", fill="both", expand=True, padx=(0,12))

        # Period buttons + date navigation
        nav_row = tk.Frame(bar_card.head, bg=C["card"]); nav_row.pack(side="right")

        self._nav_prev = SoftButton(nav_row, "◀", kind="ghost", color=C["blue"],
                                     command=lambda: self._nav_change(-1))
        self._nav_prev.pack(side="left", padx=1)
        self._nav_label = tk.Label(nav_row, text="", bg=C["card"], fg=C["text_2"],
                                    font=("Segoe UI Semibold", 9))
        self._nav_label.pack(side="left", padx=4)
        self._nav_next = SoftButton(nav_row, "▶", kind="ghost", color=C["blue"],
                                     command=lambda: self._nav_change(1))
        self._nav_next.pack(side="left", padx=1)

        tk.Frame(nav_row, bg=C["card_border"], width=1, height=20).pack(side="left", padx=6)
        for lbl, val in [("Día","day"),("Semana","week"),("Mes","month"),("Año","year")]:
            btn = tk.Radiobutton(nav_row, text=lbl, variable=self.stats_mode, value=val,
                                 indicatoron=False, bg=C["card"], fg=C["text_2"],
                                 selectcolor=C["green_lt"], activebackground=C["green_lt"],
                                 activeforeground=C["green_2"], font=("Segoe UI", 9),
                                 cursor="hand2", borderwidth=1, relief="flat", padx=12, pady=4,
                                 command=lambda: self._reload_chart())
            btn.pack(side="left", padx=2)

        self._bar = BarChart(bar_card.body, height=260); self._bar.pack(fill="both", expand=True)

        # Donut
        donut_card = Card(chart_row, title="Top productos vendidos")
        donut_card.pack(side="right", fill="both", padx=(12,0))
        donut_card.config(width=380); donut_card.pack_propagate(False)
        self._donut = DonutChart(donut_card.body, width=380, height=260)
        self._donut.pack(fill="both", expand=True)

        # Recent sales table
        recent = Card(scroll, title="Últimas ventas"); recent.pack(fill="both", expand=True, padx=24, pady=(12,24))
        cols = ("Fecha","Producto","Slot","Monto","Pago","Estado")
        widths = {"Fecha":150,"Producto":240,"Slot":60,"Monto":90,"Pago":80,"Estado":100}
        tf = tk.Frame(recent.body, bg=C["card"]); tf.pack(fill="both", expand=True)
        self._dash_tree = ModernTree(tf, cols, widths, height=8)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._dash_tree.yview)
        self._dash_tree.configure(yscrollcommand=vsb.set)
        self._dash_tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

    def _nav_change(self, direction):
        mode = self.stats_mode.get()
        if mode == "day":    self._nav_date += timedelta(days=direction)
        elif mode == "week": self._nav_date += timedelta(weeks=direction)
        elif mode == "month":
            m = self._nav_date.month + direction
            y = self._nav_date.year + (m-1)//12
            m = ((m-1) % 12) + 1
            self._nav_date = self._nav_date.replace(year=y, month=m, day=1)
        elif mode == "year":
            self._nav_date = self._nav_date.replace(year=self._nav_date.year + direction)
        self._reload_chart()

    def _reload_chart(self):
        self._nav_date = self._nav_date  # reset nothing, just reload
        threading.Thread(target=self._load_stats, daemon=True).start()

    # ──────────────────────────────────────────
    #  MACHINES
    # ──────────────────────────────────────────
    def _build_machines(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["mach"] = f
        card = Card(f, title="Máquina registrada"); card.pack(fill="both", expand=True, padx=24, pady=20)
        self._mach_status_lbl = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"],
                                          font=("Segoe UI", 10))
        self._mach_status_lbl.pack(side="left", padx=12)

        info = tk.Frame(card.body, bg=C["card"]); info.pack(fill="x", pady=(0,12))
        self._mach_vars = {}
        for i, (k, lbl, val) in enumerate([
            ("code","Código", MACHINE_CODE), ("name","Nombre","M02-UK-BC8A"),
            ("hw","Hardware","RK3568 · Android 11"), ("disp","Dispensador","/dev/ttyS4 · SH"),
            ("bill","Billetero","ICT TAO · MDB"), ("ip","IP","192.168.0.8"),
            ("status","Estado","Verificando..."), ("hb","Último heartbeat","—"),
        ]):
            row, col = i//2, i%2
            lf = tk.Frame(info, bg=C["card"]); lf.grid(row=row, column=col, sticky="w", padx=(0,40), pady=4)
            tk.Label(lf, text=f"{lbl}:", bg=C["card"], fg=C["label"],
                     font=("Segoe UI Semibold", 9)).pack(side="left")
            v = tk.StringVar(value=f"  {val}")
            tk.Label(lf, textvariable=v, bg=C["card"], fg=C["text"],
                     font=("Segoe UI", 9)).pack(side="left")
            self._mach_vars[k] = v

    # ──────────────────────────────────────────
    #  CONTROL
    # ──────────────────────────────────────────
    def _build_control(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["ctrl"] = f

        info = Card(f); info.pack(fill="x", padx=24, pady=(20,12))
        ir = tk.Frame(info.body, bg=C["card"]); ir.pack(fill="x")
        icv = tk.Canvas(ir, width=64, height=64, bg=C["card"], highlightthickness=0); icv.pack(side="left")
        icv.create_oval(4,4,60,60, fill=C["green_lt"], outline="")
        icv.create_text(32, 32, text="🏪", font=("Segoe UI Emoji", 22))
        nf = tk.Frame(ir, bg=C["card"]); nf.pack(side="left", padx=14)
        tk.Label(nf, text=f"M02-UK-BC8A ({MACHINE_CODE})", bg=C["card"], fg=C["text"],
                 font=("Segoe UI Semibold", 16)).pack(anchor="w")
        tk.Label(nf, text="RK3568 · Android 11 · Protocolo SH + MDB", bg=C["card"], fg=C["muted"],
                 font=("Segoe UI", 10)).pack(anchor="w")

        # Commands
        bottom = tk.Frame(f, bg=C["bg"]); bottom.pack(fill="both", expand=True, padx=24, pady=(0,24))
        cmd_card = Card(bottom, title="Comandos"); cmd_card.pack(side="left", fill="both", expand=True, padx=(0,12))

        cmds = [
            ("reboot","Reboot","🔄",C["amber"],True), ("update_products","Actualizar Catálogo","📥",C["blue"],False),
            ("enable_sales","Habilitar Ventas","✅",C["green"],False), ("disable_sales","Deshabilitar Ventas","⛔",C["red"],True),
            ("test_motor","Test Motor","⚙️",C["purple"],False),
        ]
        for i, (cmd,lbl,icon,color,dangerous) in enumerate(cmds):
            b = tk.Frame(cmd_card.body, bg="#f9fafb", highlightthickness=1,
                         highlightbackground=C["card_border"], cursor="hand2")
            r, c = i//2, i%2
            b.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
            cmd_card.body.columnconfigure(c, weight=1)
            inner = tk.Frame(b, bg="#f9fafb"); inner.pack(fill="both", expand=True, padx=12, pady=10)
            tk.Label(inner, text=f"{icon}  {lbl}", bg="#f9fafb", fg=C["text"],
                     font=("Segoe UI Semibold", 11)).pack(side="left")
            for w in (b, inner):
                w.bind("<Button-1>", lambda e, c=cmd, l=lbl, d=dangerous: self._send_cmd(c,l,d))

        # Log
        log_card = Card(bottom, title="Log de comandos")
        log_card.pack(side="right", fill="both", padx=(12,0)); log_card.config(width=340); log_card.pack_propagate(False)
        self._ctrl_log = scrolledtext.ScrolledText(log_card.body, bg="#f9fafb", fg=C["text"],
                                                    font=("Consolas", 9), relief="flat", state="disabled", padx=10, pady=8)
        self._ctrl_log.pack(fill="both", expand=True)
        self._ctrl_log.tag_configure("ok", foreground=C["green_2"])
        self._ctrl_log.tag_configure("err", foreground=C["red"])
        self._ctrl_log.tag_configure("ts", foreground=C["purple"])

    def _send_cmd(self, cmd, label, dangerous):
        if dangerous and not messagebox.askyesno("Confirmar", f"¿Enviar '{label}' a la máquina?"): return
        self._clog(f"→ {label}...")
        def do():
            r = self.client.send_command(cmd)
            if r and "error" not in r: self.root.after(0, lambda: self._clog(f"✅ {label} OK", "ok"))
            else: self.root.after(0, lambda: self._clog(f"❌ {label} falló (máquina offline?)", "err"))
        threading.Thread(target=do, daemon=True).start()

    def _clog(self, msg, tag="ts"):
        self._ctrl_log.config(state="normal")
        ts = datetime.now(TZ).strftime("%H:%M:%S")
        self._ctrl_log.insert("end", f"[{ts}] ", "ts")
        self._ctrl_log.insert("end", msg + "\n", tag)
        self._ctrl_log.see("end"); self._ctrl_log.config(state="disabled")

    # ──────────────────────────────────────────
    #  ORDERS
    # ──────────────────────────────────────────
    def _build_orders(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["ord"] = f
        card = Card(f, title="Historial de pedidos"); card.pack(fill="both", expand=True, padx=24, pady=20)
        self._ord_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"], font=("Segoe UI", 10))
        self._ord_count.pack(side="left", padx=12)
        SoftButton(card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_orders, daemon=True).start()).pack(side="right")
        cols = ("ID","Producto","Monto","Slot","Pago","Fecha","Estado")
        widths = {"ID":50,"Producto":240,"Monto":90,"Slot":60,"Pago":80,"Fecha":150,"Estado":100}
        tf = tk.Frame(card.body, bg=C["card"]); tf.pack(fill="both", expand=True)
        self._ord_tree = ModernTree(tf, cols, widths)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._ord_tree.yview)
        self._ord_tree.configure(yscrollcommand=vsb.set)
        self._ord_tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

    # ──────────────────────────────────────────
    #  ITEMS (Ventas reales)
    # ──────────────────────────────────────────
    def _build_items(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["items"] = f
        fb = tk.Frame(f, bg=C["bg"]); fb.pack(fill="x", padx=24, pady=(20,0))
        tk.Label(fb, text="Período:", bg=C["bg"], fg=C["text_2"],
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=(0,12))
        self._items_mode = tk.StringVar(value="all")
        for lbl, val in [("Todo","all"),("Hoy","today"),("Semana","week"),("Mes","month")]:
            btn = tk.Radiobutton(fb, text=lbl, variable=self._items_mode, value=val,
                                 indicatoron=False, bg=C["card"], fg=C["text_2"],
                                 selectcolor=C["green_lt"], activebackground=C["green_lt"],
                                 activeforeground=C["green_2"], font=("Segoe UI", 10),
                                 cursor="hand2", borderwidth=1, relief="solid", padx=14, pady=6,
                                 command=self._render_items)
            btn.pack(side="left", padx=2)

        # Resumen
        sc = Card(f, title="Resumen por artículo"); sc.pack(fill="x", padx=24, pady=(16,12))
        self._items_count = tk.Label(sc.head, text="", bg=C["card"], fg=C["muted"], font=("Segoe UI", 10))
        self._items_count.pack(side="left", padx=12)
        cols = ("Artículo","Categoría","Cant.","Ingresos","% total")
        widths = {"Artículo":250,"Categoría":160,"Cant.":100,"Ingresos":110,"% total":100}
        stf = tk.Frame(sc.body, bg=C["card"]); stf.pack(fill="both", expand=True)
        self._items_sum = ModernTree(stf, cols, widths, height=6)
        vs1 = ttk.Scrollbar(stf, orient="vertical", command=self._items_sum.yview)
        self._items_sum.configure(yscrollcommand=vs1.set)
        self._items_sum.pack(side="left", fill="both", expand=True); vs1.pack(side="right", fill="y")

        # Detalle
        dc = Card(f, title="Detalle de ventas"); dc.pack(fill="both", expand=True, padx=24, pady=(0,24))
        self._items_det_count = tk.Label(dc.head, text="", bg=C["card"], fg=C["muted"], font=("Segoe UI", 10))
        self._items_det_count.pack(side="left", padx=12)
        cols2 = ("Producto","Monto","Slot","Pago","Fecha","Estado")
        widths2 = {"Producto":240,"Monto":90,"Slot":60,"Pago":80,"Fecha":150,"Estado":100}
        dtf = tk.Frame(dc.body, bg=C["card"]); dtf.pack(fill="both", expand=True)
        self._items_det = ModernTree(dtf, cols2, widths2)
        vs2 = ttk.Scrollbar(dtf, orient="vertical", command=self._items_det.yview)
        self._items_det.configure(yscrollcommand=vs2.set)
        self._items_det.pack(side="left", fill="both", expand=True); vs2.pack(side="right", fill="y")

    # ──────────────────────────────────────────
    #  CATÁLOGO
    # ──────────────────────────────────────────
    def _build_products(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["prod"] = f
        card = Card(f, title="Catálogo de productos"); card.pack(fill="both", expand=True, padx=24, pady=20)
        self._prod_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"], font=("Segoe UI", 10))
        self._prod_count.pack(side="left", padx=12)
        cols = ("ID","Slot","Nombre","Precio","Stock","Categoría","Estado")
        widths = {"ID":50,"Slot":55,"Nombre":230,"Precio":90,"Stock":70,"Categoría":130,"Estado":80}
        tf = tk.Frame(card.body, bg=C["card"]); tf.pack(fill="both", expand=True)
        self._prod_tree = ModernTree(tf, cols, widths)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._prod_tree.yview)
        self._prod_tree.configure(yscrollcommand=vsb.set)
        self._prod_tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

    # ──────────────────────────────────────────
    #  INVENTARIO (NUEVO)
    # ──────────────────────────────────────────
    def _build_inventory(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["inv"] = f

        # Alert frame
        self._inv_alert = tk.Frame(f, bg=C["bg"]); self._inv_alert.pack(fill="x", padx=24, pady=(20,0))

        card = Card(f, title="Control de inventario")
        card.pack(fill="both", expand=True, padx=24, pady=(12,12))

        self._inv_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"], font=("Segoe UI", 10))
        self._inv_count.pack(side="left", padx=12)
        SoftButton(card.head, "↻  Actualizar", color=C["green"], kind="ghost",
                   command=self._refresh_inventory).pack(side="right")

        cols = ("Slot","Producto","Precio","Stock","Vendidos","% Disp.","Último refill")
        widths = {"Slot":55,"Producto":220,"Precio":80,"Stock":70,
                  "Vendidos":80,"% Disp.":80,"Último refill":150}
        tf = tk.Frame(card.body, bg=C["card"]); tf.pack(fill="both", expand=True)
        self._inv_tree = ModernTree(tf, cols, widths)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._inv_tree.yview)
        self._inv_tree.configure(yscrollcommand=vsb.set)
        self._inv_tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

        # Refill section
        rf = Card(f, title="Registrar reabastecimiento")
        rf.pack(fill="x", padx=24, pady=(0,20))
        row = tk.Frame(rf.body, bg=C["card"]); row.pack(fill="x")
        tk.Label(row, text="Slot:", bg=C["card"], fg=C["label"], font=("Segoe UI", 10)).pack(side="left")
        self._refill_slot = tk.Entry(row, bg="#f9fafb", fg=C["text"], font=("Segoe UI", 10),
                                      width=6, relief="flat"); self._refill_slot.pack(side="left", padx=(4,12))
        tk.Label(row, text="Cantidad:", bg=C["card"], fg=C["label"], font=("Segoe UI", 10)).pack(side="left")
        self._refill_qty = tk.Entry(row, bg="#f9fafb", fg=C["text"], font=("Segoe UI", 10),
                                     width=6, relief="flat"); self._refill_qty.pack(side="left", padx=(4,12))
        SoftButton(row, "Reabastecer", color=C["green"], command=self._do_refill).pack(side="left", padx=8)

    def _do_refill(self):
        slot = self._refill_slot.get().strip().upper()
        try: qty = int(self._refill_qty.get().strip())
        except: messagebox.showerror("Error", "Cantidad debe ser un número"); return
        if not slot: messagebox.showerror("Error", "Ingresa un slot (ej: A1)"); return

        # Find product by slot
        prods = self.products or []
        prod = next((p for p in prods if p.get("slot","").upper() == slot), None)
        if not prod: messagebox.showerror("Error", f"No hay producto en slot {slot}"); return

        def do():
            r = self.client.refill(prod["id"], slot, qty)
            if r and "error" not in r:
                self.root.after(0, lambda: (messagebox.showinfo("✅", f"Slot {slot} reabastecido a {qty} uds"),
                                             self._refresh_inventory()))
            else:
                self.root.after(0, lambda: messagebox.showerror("Error", f"No se pudo reabastecer: {r}"))
        threading.Thread(target=do, daemon=True).start()

    def _refresh_inventory(self):
        def fetch():
            inv = self.client.get_inventory()
            low = self.client.get_low_stock(3)
            prods = self.client.get_products()
            # Count total sold per product
            sales = self.client.get_sales(status="success", limit=9999)
            self.root.after(0, lambda: self._render_inventory(inv, low, prods, sales))
        threading.Thread(target=fetch, daemon=True).start()

    def _render_inventory(self, inv, low, prods, sales):
        self._inv_tree.clear()
        inv_list = (inv or {}).get("inventory", [])
        prod_list = (prods or {}).get("products", [])

        # Count sold per product
        sold_map = Counter()
        for s in (sales or {}).get("sales", []):
            sold_map[s.get("product_name","")] += 1

        for item in inv_list:
            name = item.get("name","")
            stock = item.get("stock", 0)
            max_q = item.get("max_qty", 10)
            sold = sold_map.get(name, 0)
            pct = f"{(stock/max_q*100):.0f}%" if max_q > 0 else "—"
            refill = item.get("last_refill","")
            if refill: refill = refill[:19].replace("T"," ")
            else: refill = "—"

            tag = "low_stock" if stock <= 3 else "delivered" if stock > 5 else "pending"
            self._inv_tree.add_row((
                item.get("slot",""), name, f"${item.get('price',0):,.0f}",
                stock, sold, pct, refill
            ), tags=(tag,))

        self._inv_count.config(text=f"{len(inv_list)} productos en inventario")

        # Low stock alert
        for w in self._inv_alert.winfo_children(): w.destroy()
        low_items = (low or {}).get("low_stock", [])
        if low_items:
            alert = tk.Frame(self._inv_alert, bg=C["red_lt"], padx=15, pady=8)
            alert.pack(fill="x")
            names = ", ".join(f"{i['name']} ({i['stock']})" for i in low_items[:6])
            tk.Label(alert, text=f"⚠  Stock bajo: {names}", bg=C["red_lt"], fg=C["red"],
                     font=("Segoe UI Semibold", 10), wraplength=800, justify="left").pack(anchor="w")

    # ──────────────────────────────────────────
    #  LOG
    # ──────────────────────────────────────────
    def _build_log(self):
        f = tk.Frame(self.body, bg=C["bg"]); self._tab_frames["log"] = f
        card = Card(f, title="Registro de actividad")
        card.pack(fill="both", expand=True, padx=24, pady=20)
        SoftButton(card.head, "🗑  Limpiar", color=C["red"], kind="ghost",
                   command=lambda: (self._log_txt.config(state="normal"),
                                    self._log_txt.delete("1.0","end"),
                                    self._log_txt.config(state="disabled"))).pack(side="right")
        self._log_txt = scrolledtext.ScrolledText(card.body, bg="#f9fafb", fg=C["text"],
                                                   font=("Consolas", 10), relief="flat",
                                                   state="disabled", padx=12, pady=10)
        self._log_txt.pack(fill="both", expand=True)
        self._log_txt.tag_configure("ok", foreground=C["green_2"])
        self._log_txt.tag_configure("er", foreground=C["red"])
        self._log_txt.tag_configure("in", foreground=C["blue"])
        self._log_txt.tag_configure("wr", foreground=C["amber"])
        self._log_txt.tag_configure("ts", foreground=C["purple"])

    def _log(self, msg, tag="in"):
        def do():
            if not hasattr(self, "_log_txt"): return
            self._log_txt.config(state="normal")
            ts = datetime.now(TZ).strftime("%H:%M:%S")
            self._log_txt.insert("end", f"[{ts}] ", "ts")
            self._log_txt.insert("end", msg + "\n", tag)
            self._log_txt.see("end"); self._log_txt.config(state="disabled")
        self.root.after(0, do)

    # ──────────────────────────────────────────
    #  DATA LOADING
    # ──────────────────────────────────────────
    def _start_ws(self):
        def on_msg(data):
            t = data.get("type","")
            if t in ("new_sale","sale_result"):
                self._log(f"WS: {t} — {data.get('product_name','')}", "ok")
                threading.Thread(target=self._load_all, daemon=True).start()
            elif t in ("machine_connected","machine_disconnected"):
                self._log(f"WS: máquina {t.split('_')[1]}", "in")
        self.ws = WSClient(WS_URL, on_msg=on_msg)
        self.ws.start()

    def _start_auto_refresh(self):
        def loop():
            while self.auto_refresh:
                time.sleep(30)
                if self.auto_refresh:
                    self._log("Auto-refresh...", "in")
                    threading.Thread(target=self._load_all, daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()

    def _load_all(self):
        self._log("Cargando datos...", "in")
        ok = self.client.health()
        self.root.after(0, lambda: self._draw_conn(ok))
        if not ok:
            self._log("⚠ Servidor no disponible", "er"); return

        def safe(name, fn):
            try: fn()
            except Exception as e: self._log(f"Error {name}: {e}", "er")

        threads = [
            threading.Thread(target=safe, args=("stats", self._load_stats), daemon=True),
            threading.Thread(target=safe, args=("orders", self._load_orders), daemon=True),
            threading.Thread(target=safe, args=("products", self._load_products), daemon=True),
        ]
        for t in threads: t.start()
        self.root.after(0, lambda: self._upd_lbl.config(
            text="Última sync: " + datetime.now(TZ).strftime("%H:%M:%S")))

    def _load_stats(self):
        summary = self.client.get_summary()
        mode = self.stats_mode.get()
        fmt = "%Y-%m-%dT%H:%M:%S-06:00"
        d = self._nav_date
        periods = []

        if mode == "day":
            # 24 horas de un día: no necesitamos barras por hora, solo el total
            ds = datetime(d.year, d.month, d.day, 0,0,0, tzinfo=TZ).strftime(fmt)
            de = datetime(d.year, d.month, d.day, 23,59,59, tzinfo=TZ).strftime(fmt)
            periods = [{"startTime": ds, "endTime": de}]
        elif mode == "week":
            # 7 días de la semana seleccionada (cada barra = 1 día)
            dow = d.weekday()  # 0=Monday
            start = d - timedelta(days=dow)
            for i in range(7):
                dd = start + timedelta(days=i)
                ds = datetime(dd.year, dd.month, dd.day, 0,0,0, tzinfo=TZ).strftime(fmt)
                de = datetime(dd.year, dd.month, dd.day, 23,59,59, tzinfo=TZ).strftime(fmt)
                periods.append({"startTime": ds, "endTime": de})
        elif mode == "month":
            # Cada día del mes seleccionado
            import calendar
            _, last_day = calendar.monthrange(d.year, d.month)
            for day in range(1, last_day+1):
                ds = datetime(d.year, d.month, day, 0,0,0, tzinfo=TZ).strftime(fmt)
                de = datetime(d.year, d.month, day, 23,59,59, tzinfo=TZ).strftime(fmt)
                periods.append({"startTime": ds, "endTime": de})
        elif mode == "year":
            # 12 meses del año seleccionado
            import calendar
            for m in range(1, 13):
                _, last = calendar.monthrange(d.year, m)
                ds = datetime(d.year, m, 1, 0,0,0, tzinfo=TZ).strftime(fmt)
                de = datetime(d.year, m, last, 23,59,59, tzinfo=TZ).strftime(fmt)
                periods.append({"startTime": ds, "endTime": de})

        chart = self.client.get_stats_periods(periods)
        self.root.after(0, lambda: self._apply_stats(summary, chart, periods, mode))

    def _apply_stats(self, summary, chart, periods, mode):
        if isinstance(summary, dict) and "today" in summary:
            td = summary.get("today", {}); mn = summary.get("month", {})
            self._kpi["rev_day"].set(f"${int(td.get('saleAmount',0)):,}")
            self._kpi["cnt_day"].set(str(td.get("saleCount",0)))
            self._kpi["rev_month"].set(f"${int(mn.get('saleAmount',0)):,}", "MXN")
            self._kpi["cnt_month"].set(str(mn.get("saleCount",0)), f"{mn.get('saleCount',0)} ventas")
            self._kpi["online"].set("En línea", "Servidor local")
            self._draw_conn(True)
            self._log(f"Stats: hoy={td.get('saleCount',0)} (${int(td.get('saleAmount',0)):,}) "
                      f"| mes={mn.get('saleCount',0)} (${int(mn.get('saleAmount',0)):,})", "ok")

        # Update nav label
        d = self._nav_date
        MESES = ["","Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        if mode == "day":
            self._nav_label.config(text=d.strftime("%d/%m/%Y"))
        elif mode == "week":
            dow = d.weekday()
            ws = d - timedelta(days=dow); we = ws + timedelta(days=6)
            self._nav_label.config(text=f"{ws.strftime('%d/%m')} — {we.strftime('%d/%m/%Y')}")
        elif mode == "month":
            self._nav_label.config(text=f"{MESES[d.month]} {d.year}")
        elif mode == "year":
            self._nav_label.config(text=str(d.year))

        # Bar chart
        if isinstance(chart, dict) and "data" in chart:
            cdata = chart["data"]
            vals = [float(x.get("saleAmount",0) or 0) for x in cdata]
            if mode == "day":
                lbls = [d.strftime("%d %b")]; color = C["bar_a"]
            elif mode == "week":
                DIAS = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
                dow = d.weekday()
                ws = d - timedelta(days=dow)
                lbls = [(ws+timedelta(days=i)).strftime(f"{DIAS[i]} %d") for i in range(len(periods))]
                color = C["bar_b"]
            elif mode == "month":
                lbls = [str(i+1) for i in range(len(periods))]; color = C["bar_c"]
            elif mode == "year":
                lbls = ["E","F","M","A","M","J","J","A","S","O","N","D"][:len(periods)]
                color = C["bar_d"]
            else:
                lbls = [str(i) for i in range(len(vals))]; color = C["bar_a"]
            self._bar.set_data(vals, lbls, color)

    def _load_orders(self):
        d = self.client.get_sales(status=None, limit=500)
        if not d or "error" in d: self._log(f"Error pedidos: {d}", "er"); return
        self.sales = d.get("sales", [])
        self.root.after(0, lambda: self._render_orders(self.sales))
        self.root.after(0, self._render_items)
        self.root.after(0, self._render_dash_recent)
        self.root.after(0, self._render_donut)

    def _render_orders(self, lst):
        self._ord_tree.clear()
        for s in lst:
            ts = (s.get("created_at","") or "")[:19].replace("T"," ")
            st = s.get("status",""); tag = "delivered" if st=="success" else ("fail" if st=="failed" else "pending")
            st_txt = {"success":"Entregado","failed":"Fallo","pending":"Pendiente"}.get(st, st)
            self._ord_tree.add_row((
                s.get("id",""), s.get("product_name",""), f"${s.get('amount',0):,.0f}",
                s.get("slot",""), s.get("payment_type",""), ts, st_txt
            ), tags=(tag,))
        self._ord_count.config(text=f"{len(lst)} pedidos")
        self._log(f"{len(lst)} pedidos cargados", "ok")

    def _render_dash_recent(self):
        self._dash_tree.clear()
        delivered = [s for s in self.sales if s.get("status") == "success"]
        for s in delivered[:15]:
            ts = (s.get("created_at","") or "")[:19].replace("T"," ")
            self._dash_tree.add_row((
                ts, s.get("product_name",""), s.get("slot",""),
                f"${s.get('amount',0):,.0f}", s.get("payment_type","cash"), "Entregado"
            ), tags=("delivered",))

    def _render_donut(self):
        counts = Counter()
        for s in self.sales:
            if s.get("status") == "success":
                counts[s.get("product_name","")] += 1
        top = counts.most_common(5)
        colors = [C["green"], C["blue"], C["amber"], C["purple"], C["pink"]]
        self._donut.set_data([(n,q,colors[i%len(colors)]) for i,(n,q) in enumerate(top)])

    def _render_items(self):
        if not hasattr(self, "_items_sum"): return
        now_tz = datetime.now(TZ); today = now_tz.date()
        mode = self._items_mode.get()
        items = []
        for s in self.sales:
            if s.get("status") != "success": continue
            raw = s.get("created_at","") or ""
            try:
                dt = datetime.fromisoformat(raw)
                dt_date = dt.date()
            except: continue

            if mode == "today" and dt_date != today: continue
            elif mode == "week" and (today-dt_date).days > 6: continue
            elif mode == "month" and (dt_date.year != today.year or dt_date.month != today.month): continue

            items.append(s)

        # Summary
        summary = {}
        total_rev = sum(float(i.get("amount",0)) for i in items)
        for it in items:
            k = it.get("product_name","")
            if k not in summary: summary[k] = {"name":k, "qty":0, "rev":0.0}
            summary[k]["qty"] += 1; summary[k]["rev"] += float(it.get("amount",0))

        self._items_sum.clear()
        for sv in sorted(summary.values(), key=lambda x:-x["rev"]):
            pct = f"{sv['rev']/total_rev*100:.1f}%" if total_rev > 0 else "—"
            self._items_sum.add_row((sv["name"],"", str(sv["qty"]), f"${sv['rev']:,.0f}", pct))
        self._items_count.config(text=f"{len(summary)} artículos · {len(items)} ventas · ${total_rev:,.0f}")

        self._items_det.clear()
        for it in items:
            ts = (it.get("created_at","") or "")[:19].replace("T"," ")
            self._items_det.add_row((
                it.get("product_name",""), f"${it.get('amount',0):,.0f}",
                it.get("slot",""), it.get("payment_type",""), ts, "Entregado"
            ), tags=("delivered",))
        self._items_det_count.config(text=f"{len(items)} ventas en este período")

    def _load_products(self):
        d = self.client.get_products()
        if not d or "error" in d: self._log(f"Error productos: {d}", "er"); return
        self.products = d.get("products", [])
        self.root.after(0, lambda: self._render_products(self.products))

    def _render_products(self, lst):
        self._prod_tree.clear()
        for p in lst:
            st = "Activo" if p.get("active") else "Inactivo"
            tag = "delivered" if p.get("active") else "fail"
            self._prod_tree.add_row((
                p.get("id",""), p.get("slot",""), p.get("name",""),
                f"${p.get('price',0):,.0f}", p.get("stock","—"),
                p.get("category",""), st
            ), tags=(tag,))
        self._prod_count.config(text=f"{len(lst)} productos")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import traceback
    try:
        # Check server
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=3)
            server_ok = r.status_code == 200
        except: server_ok = False

        if not server_ok:
            messagebox.showwarning("Servidor no detectado",
                f"No se pudo conectar al servidor en {BASE_URL}\n\n"
                "Asegúrate de ejecutar VMC-Server.bat primero.\n"
                "La app intentará reconectarse automáticamente.")

        root = tk.Tk()
        try: root.tk.call("tk", "scaling", DPI_SCALE * 1.333)
        except: pass

        app = VMCDesktop(root)
        def on_close():
            app.auto_refresh = False
            if app.ws: app.ws.stop()
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

    except Exception as e:
        err = traceback.format_exc()
        try:
            with open(os.path.join(SCRIPT_DIR, "error.log"), "w", encoding="utf-8") as f: f.write(err)
        except: pass
        try:
            er = tk.Tk(); er.title("VMC Error"); er.geometry("720x520"); er.configure(bg="#f4f6fa")
            tk.Label(er, text="Error al iniciar", bg="#f4f6fa", fg="#ef4444",
                     font=("Segoe UI", 14, "bold")).pack(pady=14)
            t = scrolledtext.ScrolledText(er, bg="#fff", fg="#1f2937", font=("Consolas", 9))
            t.pack(fill="both", expand=True, padx=18, pady=8); t.insert("1.0", err); t.config(state="disabled")
            tk.Button(er, text="Cerrar", command=er.destroy, bg="#ef4444", fg="white",
                      font=("Segoe UI", 10, "bold"), relief="flat", padx=20, pady=6).pack(pady=12)
            er.mainloop()
        except: print(err)
        sys.exit(1)
