#!/usr/bin/env python3
"""
VMC Control Center Desktop v3
Dashboard profesional para máquinas expendedoras — con HiDPI
"""
import os, sys

# ═══════════════════════════════════════════════════════════════
#  HIGH DPI / RETINA SUPPORT (debe ir ANTES de importar tkinter)
# ═══════════════════════════════════════════════════════════════
# En Windows: avisar al sistema que la app maneja DPI por sí misma
# Esto evita que Windows escale la app con bilinear filtering (= pixeleado)
if sys.platform == "win32":
    try:
        from ctypes import windll
        # PROCESS_PER_MONITOR_DPI_AWARE (Windows 8.1+)
        # Hace que la app reciba coordenadas reales y no escaladas
        try:
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            # Fallback para Windows 7/8: PROCESS_SYSTEM_DPI_AWARE
            try:    windll.shcore.SetProcessDpiAwareness(1)
            except: windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading, urllib.request, urllib.error
import json, time, math, webbrowser
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════
#  DPI AWARENESS — Activar antes de crear la ventana Tk
#  Esto elimina el pixeleado en pantallas de alta resolucion
# ══════════════════════════════════════════════════════════
def _enable_dpi_awareness():
    """Activa DPI awareness en Windows para renderizar nitido."""
    if sys.platform != "win32":
        return 1.0
    try:
        from ctypes import windll
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 8.1+)
        # PROCESS_SYSTEM_DPI_AWARE = 1
        try:
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        # Obtener el factor de escala actual
        try:
            hdc = windll.user32.GetDC(0)
            # 88 = LOGPIXELSX
            dpi_x = windll.gdi32.GetDeviceCaps(hdc, 88)
            windll.user32.ReleaseDC(0, hdc)
            return dpi_x / 96.0
        except Exception:
            return 1.0
    except Exception:
        return 1.0

DPI_SCALE = _enable_dpi_awareness()

# ══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════
API = "https://api.vmc002.csmology.com"
TZ  = timezone(timedelta(hours=-6))

try:
    if getattr(sys, 'frozen', False):
        SCRIPT_DIR = os.path.dirname(sys.executable)
    else:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.txt")

_token_lock = threading.Lock()
_current_token = {"value": None}

def load_token_from_file():
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
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token if token.startswith("Bearer ") else "Bearer " + token)
        return True
    except Exception:
        return False

# ══════════════════════════════════════════════════════════
#  PALETA DE COLORES — Estilo BI claro
# ══════════════════════════════════════════════════════════
C = {
    # Fondos
    "bg":          "#f4f6fa",   # fondo general (claro)
    "card":        "#ffffff",   # tarjetas
    "card_border": "#e2e8f0",   # borde sutil
    "header":      "#ffffff",   # barra superior
    "sidebar":     "#1e2233",   # barra lateral oscura
    "sidebar_hov": "#2a3047",
    "sidebar_act": "#00a884",   # tab activo

    # Texto
    "text":     "#1f2937",
    "text_2":   "#4b5563",
    "muted":    "#9ca3af",
    "label":    "#6b7280",

    # Acentos (estilo Triskell)
    "green":    "#00c896",      # verde principal
    "green_2":  "#00a884",
    "green_lt": "#dcfce7",
    "red":      "#ef4444",
    "red_lt":   "#fee2e2",
    "amber":    "#f59e0b",
    "amber_lt": "#fef3c7",
    "blue":     "#3b82f6",
    "blue_lt":  "#dbeafe",
    "purple":   "#8b5cf6",
    "purple_lt":"#ede9fe",
    "pink":     "#ec4899",
    "teal":     "#14b8a6",

    # Datos / gráficas
    "bar_a":    "#10b981",
    "bar_b":    "#3b82f6",
    "bar_c":    "#f59e0b",
    "bar_d":    "#8b5cf6",
}

CMDS = {
    "0100": ("Normal Service",   "✅", False, C["green"]),
    "0101": ("Out of Service",   "⚠️", True,  C["amber"]),
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
        with _token_lock:
            if _current_token.get("value"):
                return _current_token["value"]
            t = load_token_from_file()
            if t:
                _current_token["value"] = t
            return _current_token.get("value")

    def invalidate_token(self):
        with _token_lock:
            _current_token["value"] = None

    def req(self, method, path, body=None):
        token = self._get_token()
        if not token:
            return {"error": "NO_TOKEN"}
        url  = API + path
        data = json.dumps(body).encode() if body is not None else None
        r    = urllib.request.Request(url, data=data, method=method)
        r.add_header("Content-Type",  "application/json")
        r.add_header("Authorization", token)
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                if isinstance(result, list):
                    return {"_list": result, "_ok": True}
                return result
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.invalidate_token()
                return {"error": "TOKEN_EXPIRED"}
            try:    return json.loads(e.read().decode())
            except: return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def get_stats(self, mode="day"):
        now = datetime.now(TZ)
        fmt = "%Y-%m-%dT%H:%M:%S-06:00"
        today_s = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=TZ).strftime(fmt)
        today_e = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=TZ).strftime(fmt)
        month_s = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=TZ).strftime(fmt)

        summary_periods = [
            {"startTime": today_s, "endTime": today_e},
            {"startTime": month_s, "endTime": today_e},
        ]
        summary = self.req("POST", "/api/statistics/getSaleCount",
                           {"timePeriodList": summary_periods, "groupIds": "", "machineIds": ""})

        chart_periods = []
        if mode == "day":
            chart_periods.append({"startTime": today_s, "endTime": today_e})
        elif mode == "week":
            for i in range(6, -1, -1):
                d = now - timedelta(days=i)
                s = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ).strftime(fmt)
                e = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ).strftime(fmt)
                chart_periods.append({"startTime": s, "endTime": e})
        elif mode == "month":
            chart_periods.append({"startTime": month_s, "endTime": today_e})

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
#  CANVAS GRÁFICAS PROFESIONALES
# ══════════════════════════════════════════════════════════
class BarChart(tk.Canvas):
    """Gráfica de barras tipo BI con valores y ejes."""
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["card"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._data = []
        self._labels = []
        self._color = C["bar_a"]
        self._title = ""
        self._unit = "$"
        # Calidad: usar el factor de escala para tamaños nítidos
        try:
            self._dpi_scale = self.tk.call("tk", "scaling")
        except: self._dpi_scale = 1.0
        self.bind("<Configure>", lambda e: self._draw())

    def set_data(self, values, labels, color=None, unit="$"):
        self._data = values or []
        self._labels = labels or []
        self._color = color or C["bar_a"]
        self._unit = unit
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or 600
        h = self.winfo_height() or 280
        if not self._data:
            self.create_text(w/2, h/2, text="Sin datos", fill=C["muted"], font=("Segoe UI", 11))
            return

        # Márgenes
        ml, mr, mt, mb = 60, 30, 30, 50
        chart_w = w - ml - mr
        chart_h = h - mt - mb

        max_v = max(self._data) if max(self._data) > 0 else 1
        # Redondear máximo a número "bonito"
        nice_max = self._nice_max(max_v)

        # Lineas de grid horizontales con etiquetas (float para suavizado)
        for i in range(5):
            v = nice_max * (4-i) / 4
            y = mt + chart_h * i / 4.0
            self.create_line(ml, y, w-mr, y, fill=C["card_border"], width=1)
            self.create_text(ml-10, y, text=f"{int(v):,}", fill=C["label"],
                             font=("Segoe UI", 9), anchor="e")

        # Linea cero mas fuerte
        zero_y = mt + chart_h
        self.create_line(ml, zero_y, w-mr, zero_y, fill=C["text_2"], width=2)

        # Barras
        n = len(self._data)
        bar_space = chart_w / n
        bar_w = min(50, bar_space * 0.55)

        for i, v in enumerate(self._data):
            cx = ml + bar_space * (i + 0.5)
            x0 = cx - bar_w / 2
            x1 = cx + bar_w / 2
            bar_h = (v / nice_max) * chart_h if nice_max > 0 else 0
            y0 = zero_y - bar_h

            # Sombra suave
            self.create_rectangle(x0+2, y0+2, x1+2, zero_y, fill="#e2e8f0", outline="")
            # Barra
            self.create_rectangle(x0, y0, x1, zero_y, fill=self._color, outline="")
            # Brillo arriba
            self.create_rectangle(x0, y0, x1, y0+3, fill=self._lighten(self._color), outline="")

            # Valor encima
            if v > 0:
                self.create_text(cx, y0-8, text=f"{self._unit}{int(v):,}",
                                 fill=C["text"], font=("Segoe UI Semibold", 10), anchor="s")

            # Etiqueta abajo
            if i < len(self._labels):
                self.create_text(cx, zero_y+10, text=self._labels[i],
                                 fill=C["label"], font=("Segoe UI", 10), anchor="n")

    @staticmethod
    def _nice_max(v):
        if v <= 0: return 100
        magnitude = 10 ** int(math.log10(v))
        for mult in [1, 1.5, 2, 2.5, 3, 5, 7.5, 10]:
            if v <= mult * magnitude:
                return mult * magnitude
        return 10 * magnitude

    @staticmethod
    def _lighten(hex_color, amount=40):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = min(255, r + amount); g = min(255, g + amount); b = min(255, b + amount)
        return f"#{r:02x}{g:02x}{b:02x}"


class DonutChart(tk.Canvas):
    """Gráfica de dona estilo BI con leyenda."""
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["card"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._data = []  # lista de (label, value, color)
        self._title = ""
        self.bind("<Configure>", lambda e: self._draw())

    def set_data(self, data):
        self._data = data or []
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or 300
        h = self.winfo_height() or 280
        if not self._data:
            self.create_text(w/2, h/2, text="Sin datos", fill=C["muted"],
                             font=("Segoe UI", 11))
            return

        total = sum(v for _, v, _ in self._data) or 1
        # Centro y radio (la dona ocupa la mitad izquierda)
        chart_w = w * 0.55
        cx = chart_w / 2
        cy = h / 2
        r_out = min(chart_w, h) / 2 - 24
        r_in = r_out * 0.62

        # Dibujar arcos con bordes blancos para separar segmentos
        start = 90  # empezar arriba
        for label, value, color in self._data:
            extent = -360 * (value / total)
            self.create_arc(cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                            start=start, extent=extent, fill=color,
                            outline="white", width=3, style="pieslice")
            start += extent

        # Hueco interior (efecto dona)
        self.create_oval(cx - r_in, cy - r_in, cx + r_in, cy + r_in,
                         fill=C["card"], outline="")

        # Total en el centro
        self.create_text(cx, cy - 12, text=f"{int(total)}",
                         fill=C["text"], font=("Segoe UI", 24, "bold"))
        self.create_text(cx, cy + 16, text="TOTAL",
                         fill=C["muted"], font=("Segoe UI Semibold", 9))

        # Leyenda a la derecha con mejor alineacion
        lx = chart_w + 12
        ly = 28
        line_h = 38
        for label, value, color in self._data:
            pct = (value / total * 100) if total else 0
            # Cuadro de color redondeado
            self.create_rectangle(lx, ly + 2, lx + 14, ly + 14,
                                  fill=color, outline="")
            # Nombre del producto (truncar si es muy largo)
            display_name = label if len(label) <= 22 else label[:20] + "..."
            self.create_text(lx + 22, ly + 1, text=display_name,
                             fill=C["text"], font=("Segoe UI Semibold", 10),
                             anchor="nw")
            # Cantidad y porcentaje
            self.create_text(lx + 22, ly + 18, text=f"{int(value)} unidades  ·  {pct:.1f}%",
                             fill=C["muted"], font=("Segoe UI", 9), anchor="nw")
            ly += line_h


# ══════════════════════════════════════════════════════════
#  WIDGETS PERSONALIZADOS
# ══════════════════════════════════════════════════════════
class KPICard(tk.Frame):
    """Tarjeta KPI estilo BI con icono, valor y etiqueta."""
    def __init__(self, parent, label, icon, color):
        super().__init__(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["card_border"])
        self._color = color
        self._color_lt = color + "20"  # tinte claro

        # Layout interno
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=18, pady=14)

        # Header con icono coloreado
        header = tk.Frame(inner, bg=C["card"])
        header.pack(fill="x")

        icon_box = tk.Frame(header, bg=C["card"], width=44, height=44)
        icon_box.pack(side="left")
        icon_box.pack_propagate(False)
        # Circulo de color con icono - dibujado con doble resolucion para suavizar
        canvas = tk.Canvas(icon_box, width=44, height=44, bg=C["card"], highlightthickness=0)
        canvas.pack()
        # Multiples ovalos para simular antialiasing
        canvas.create_oval(2, 2, 42, 42, fill=self._tint(color), outline=color, width=0)
        canvas.create_text(22, 22, text=icon, font=("Segoe UI Emoji", 16))

        tk.Label(header, text=label.upper(), bg=C["card"], fg=C["label"],
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(10,0), pady=(8,0), anchor="nw")

        # Valor grande
        self.val_var = tk.StringVar(value="—")
        tk.Label(inner, textvariable=self.val_var, bg=C["card"], fg=C["text"],
                 font=("Segoe UI", 28, "bold")).pack(anchor="w", pady=(8,0))

        # Subtitulo
        self.sub_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.sub_var, bg=C["card"], fg=color,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")

    @staticmethod
    def _tint(hex_color):
        """Crea versión tintada (con alpha) del color."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Mezclar con blanco al 85%
        r = int(r * 0.18 + 255 * 0.82)
        g = int(g * 0.18 + 255 * 0.82)
        b = int(b * 0.18 + 255 * 0.82)
        return f"#{r:02x}{g:02x}{b:02x}"

    def set(self, val, sub=""):
        self.val_var.set(val)
        self.sub_var.set(sub)


class Card(tk.Frame):
    """Tarjeta blanca con título — contenedor estándar."""
    def __init__(self, parent, title=None, **kw):
        kw.setdefault("bg", C["card"])
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", C["card_border"])
        super().__init__(parent, **kw)
        if title:
            head = tk.Frame(self, bg=C["card"])
            head.pack(fill="x", padx=18, pady=(14, 0))
            tk.Label(head, text=title, bg=C["card"], fg=C["text"],
                     font=("Segoe UI Semibold", 12)).pack(side="left")
            self.head = head
        # Contenedor para body
        self.body = tk.Frame(self, bg=C["card"])
        self.body.pack(fill="both", expand=True, padx=18, pady=(8, 14))


class SoftButton(tk.Button):
    """Botón con estilo suave estilo BI."""
    def __init__(self, parent, text, command=None, color=None, kind="solid", **kw):
        bg = color or C["green"]
        if kind == "solid":
            kw.update(dict(bg=bg, fg="white" if bg != C["amber"] else C["text"],
                           activebackground=bg, activeforeground="white"))
            self._hover_bg = self._darken(bg)
        else:  # ghost
            kw.update(dict(bg=C["card"], fg=bg,
                           activebackground=C["card"], activeforeground=bg))
            self._hover_bg = "#f3f4f6"
        kw.update(dict(text=text, command=command or (lambda: None),
                       font=("Segoe UI Semibold", 10), relief="flat",
                       cursor="hand2", padx=14, pady=7, bd=0))
        super().__init__(parent, **kw)
        self._normal_bg = self.cget("bg")
        self.bind("<Enter>", lambda e: self.config(bg=self._hover_bg))
        self.bind("<Leave>", lambda e: self.config(bg=self._normal_bg))

    @staticmethod
    def _darken(hex_color):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = max(0, r - 25); g = max(0, g - 25); b = max(0, b - 25)
        return f"#{r:02x}{g:02x}{b:02x}"


class ModernTree(ttk.Treeview):
    _styled = False

    def __init__(self, parent, columns, col_widths=None, **kw):
        if not ModernTree._styled:
            s = ttk.Style()
            s.theme_use("clam")  # 'clam' tiene mejor calidad visual que 'default'
            # Filas alternas, fuente nitida, mas espacio
            s.configure("BI.Treeview",
                        background=C["card"], foreground=C["text"],
                        fieldbackground=C["card"], rowheight=36,
                        font=("Segoe UI", 10), borderwidth=0,
                        relief="flat")
            s.configure("BI.Treeview.Heading",
                        background="#f9fafb", foreground=C["label"],
                        font=("Segoe UI Semibold", 9), relief="flat",
                        padding=(10, 10), borderwidth=0)
            s.map("BI.Treeview.Heading",
                  background=[("active", "#f3f4f6")])
            s.map("BI.Treeview",
                  background=[("selected", C["green_lt"])],
                  foreground=[("selected", C["text"])])
            s.layout("BI.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            # Scrollbar mas elegante
            s.configure("Vertical.TScrollbar",
                        background="#e5e7eb", troughcolor=C["card"],
                        borderwidth=0, arrowsize=14, relief="flat")
            s.configure("Horizontal.TScrollbar",
                        background="#e5e7eb", troughcolor=C["card"],
                        borderwidth=0, arrowsize=14, relief="flat")
            ModernTree._styled = True

        super().__init__(parent, columns=columns, show="headings",
                         style="BI.Treeview", **kw)
        for col in columns:
            w = (col_widths or {}).get(col, 120)
            self.heading(col, text=col)
            self.column(col, width=w, minwidth=60)

        # Tags de color
        self.tag_configure("delivered", foreground=C["green_2"], font=("Segoe UI Semibold", 10))
        self.tag_configure("pending",   foreground=C["amber"],   font=("Segoe UI Semibold", 10))
        self.tag_configure("fail",      foreground=C["red"],     font=("Segoe UI Semibold", 10))
        self.tag_configure("online",    foreground=C["green_2"], font=("Segoe UI Semibold", 10))
        self.tag_configure("offline",   foreground=C["red"],     font=("Segoe UI Semibold", 10))
        self.tag_configure("alt",       background="#fafbfc")

    def clear(self):
        self.delete(*self.get_children())

    def add_row(self, values, tags=()):
        idx = len(self.get_children())
        all_tags = list(tags) + (["alt"] if idx % 2 == 1 else [])
        self.insert("", "end", values=values, tags=all_tags)


class Sidebar(tk.Frame):
    """Sidebar oscura con iconos, estilo Triskell."""
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=C["sidebar"], width=72)
        self.pack_propagate(False)
        self._on_select = on_select
        self._buttons = {}
        self._active = None

        # Logo arriba
        logo = tk.Frame(self, bg=C["sidebar"], height=72)
        logo.pack(fill="x")
        logo.pack_propagate(False)
        tk.Label(logo, text="VMC", bg=C["sidebar"], fg=C["green"],
                 font=("Consolas", 16, "bold")).pack(pady=22)

        # Items
        self.items_frame = tk.Frame(self, bg=C["sidebar"])
        self.items_frame.pack(fill="both", expand=True)

    def add_item(self, key, icon, label):
        btn = tk.Frame(self.items_frame, bg=C["sidebar"], height=56, cursor="hand2")
        btn.pack(fill="x")
        btn.pack_propagate(False)

        # Indicador izquierdo (línea verde cuando activo)
        indicator = tk.Frame(btn, bg=C["sidebar"], width=3)
        indicator.pack(side="left", fill="y")

        # Icono centrado
        icon_lbl = tk.Label(btn, text=icon, bg=C["sidebar"], fg="#7a8299",
                            font=("Segoe UI Emoji", 18))
        icon_lbl.pack(expand=True)

        def on_enter(e):
            if self._active != key:
                btn.config(bg=C["sidebar_hov"])
                icon_lbl.config(bg=C["sidebar_hov"])
                indicator.config(bg=C["sidebar_hov"])
        def on_leave(e):
            if self._active != key:
                btn.config(bg=C["sidebar"])
                icon_lbl.config(bg=C["sidebar"])
                indicator.config(bg=C["sidebar"])
        def on_click(e):
            self.set_active(key)
            self._on_select(key)

        for w in (btn, icon_lbl, indicator):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

        self._buttons[key] = (btn, icon_lbl, indicator, label)
        if not self._active:
            self.set_active(key)

    def set_active(self, key):
        # Resetear todos
        for k, (btn, icon_lbl, indicator, _) in self._buttons.items():
            btn.config(bg=C["sidebar"])
            icon_lbl.config(bg=C["sidebar"], fg="#7a8299")
            indicator.config(bg=C["sidebar"])
        # Activar nuevo
        if key in self._buttons:
            btn, icon_lbl, indicator, _ = self._buttons[key]
            btn.config(bg=C["sidebar_hov"])
            icon_lbl.config(bg=C["sidebar_hov"], fg=C["green"])
            indicator.config(bg=C["green"])
        self._active = key


# ══════════════════════════════════════════════════════════
#  APP PRINCIPAL
# ══════════════════════════════════════════════════════════
class VMCDesktop:
    def __init__(self, root):
        self.root = root
        self.client = API_Client()
        self.sel_mach = None
        self.machines = []
        self.orders = []
        self.products = []
        self.rep = []
        self.stats_mode = tk.StringVar(value="week")
        self.auto_refresh = True
        self._current_tab = None
        self._tab_frames = {}

        self._setup_window()
        self._build()
        self._show_tab("dash")
        self._start_auto_refresh()
        self.root.after(300, lambda: threading.Thread(target=self._load_all, daemon=True).start())

    def _setup_window(self):
        self.root.title("VMC Control Center")
        # Ajustar tamano segun DPI scale para que se vea bien en cualquier monitor
        w = int(1280 * max(1.0, DPI_SCALE * 0.85))
        h = int(800  * max(1.0, DPI_SCALE * 0.85))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(1100 * max(1.0, DPI_SCALE * 0.8)), int(700 * max(1.0, DPI_SCALE * 0.8)))
        self.root.configure(bg=C["bg"])
        # Ajuste fino de tipografias en HiDPI
        try:
            from tkinter import font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family="Segoe UI")
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(family="Segoe UI")
        except Exception:
            pass

    def _build(self):
        # Layout principal: sidebar + content
        main_frame = tk.Frame(self.root, bg=C["bg"])
        main_frame.pack(fill="both", expand=True)

        # Sidebar
        self.sidebar = Sidebar(main_frame, on_select=self._show_tab)
        self.sidebar.pack(side="left", fill="y")

        # Área de contenido
        content = tk.Frame(main_frame, bg=C["bg"])
        content.pack(side="left", fill="both", expand=True)

        # Top bar
        topbar = tk.Frame(content, bg=C["header"], height=56,
                          highlightthickness=1, highlightbackground=C["card_border"])
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        # Breadcrumb / título dinámico
        self._title_var = tk.StringVar(value="Dashboard")
        title_frame = tk.Frame(topbar, bg=C["header"])
        title_frame.pack(side="left", padx=20, pady=14)
        tk.Label(title_frame, text="VMC Control Center", bg=C["header"], fg=C["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(title_frame, textvariable=self._title_var, bg=C["header"], fg=C["text"],
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")

        # Right side: connection + refresh + last update
        right = tk.Frame(topbar, bg=C["header"])
        right.pack(side="right", padx=20, pady=12)

        self._upd_lbl = tk.Label(right, text="", bg=C["header"], fg=C["muted"],
                                 font=("Segoe UI", 9))
        self._upd_lbl.pack(side="left", padx=(0, 12))

        self._conn_canvas = tk.Canvas(right, width=110, height=28, bg=C["header"],
                                      highlightthickness=0)
        self._conn_canvas.pack(side="left", padx=8)
        self._draw_conn_badge(False)

        SoftButton(right, "↻  Actualizar",
                   command=lambda: threading.Thread(target=self._load_all, daemon=True).start(),
                   color=C["green"]
                   ).pack(side="left", padx=4)

        # Content body — un Frame contenedor donde alternamos las pestañas
        self.body = tk.Frame(content, bg=C["bg"])
        self.body.pack(fill="both", expand=True)

        # Construir todas las pestañas (ocultas)
        self._build_dashboard()
        self._build_machines()
        self._build_control()
        self._build_orders()
        self._build_items()
        self._build_products()
        self._build_replenishment()
        self._build_log()

        # Sidebar items (en el orden visible)
        self.sidebar.add_item("dash",  "📊", "Dashboard")
        self.sidebar.add_item("mach",  "🏪", "Máquinas")
        self.sidebar.add_item("ctrl",  "🎮", "Control")
        self.sidebar.add_item("ord",   "🧾", "Pedidos")
        self.sidebar.add_item("items", "📦", "Ventas")
        self.sidebar.add_item("prod",  "🗂", "Catálogo")
        self.sidebar.add_item("rep",   "🔄", "Reabast.")
        self.sidebar.add_item("log",   "📋", "Log")

    def _draw_conn_badge(self, ok):
        c = self._conn_canvas
        c.delete("all")
        bg = C["green_lt"] if ok else C["red_lt"]
        fg = C["green_2"] if ok else C["red"]
        text = "● En línea" if ok else "● Sin conexión"
        c.create_rectangle(0, 4, 110, 24, fill=bg, outline="", width=0)
        c.create_text(55, 14, text=text, fill=fg, font=("Segoe UI Semibold", 9))

    def _show_tab(self, key):
        # Ocultar todas
        for k, frame in self._tab_frames.items():
            frame.pack_forget()
        # Mostrar la seleccionada
        if key in self._tab_frames:
            self._tab_frames[key].pack(fill="both", expand=True)
        self._current_tab = key

        # Actualizar título
        titles = {"dash": "Dashboard", "mach": "Máquinas registradas",
                  "ctrl": "Panel de control", "ord": "Historial de pedidos",
                  "items": "Ventas reales · Artículos entregados",
                  "prod": "Catálogo de productos", "rep": "Reabastecimiento",
                  "log": "Registro de actividad"}
        self._title_var.set(titles.get(key, ""))

        # Refrescar items al entrar
        if key == "items":
            self._render_items()
        elif key == "mach":
            self._render_machines(self.machines)

    # ══════════════════════════════════════════════════
    #  DASHBOARD
    # ══════════════════════════════════════════════════
    def _build_dashboard(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["dash"] = f

        scroll = self._make_scrollable(f)

        # === KPI CARDS (fila superior) ===
        kpi_row = tk.Frame(scroll, bg=C["bg"])
        kpi_row.pack(fill="x", padx=24, pady=(20, 12))

        self._sc = {
            "rev_day":   KPICard(kpi_row, "Ingresos hoy",     "💰", C["green"]),
            "cnt_day":   KPICard(kpi_row, "Ventas hoy",       "🛒", C["blue"]),
            "cnt_month": KPICard(kpi_row, "Ventas del mes",   "📅", C["purple"]),
            "rev_month": KPICard(kpi_row, "Monto del mes",    "💵", C["amber"]),
            "online":    KPICard(kpi_row, "Máquinas online",  "🏪", C["teal"]),
        }
        for i, (_, card) in enumerate(self._sc.items()):
            card.grid(row=0, column=i, padx=6, sticky="nsew", ipady=2)
            kpi_row.columnconfigure(i, weight=1)

        # === GRÁFICA + DONA (segunda fila) ===
        chart_row = tk.Frame(scroll, bg=C["bg"])
        chart_row.pack(fill="x", padx=24, pady=12)

        # Gráfica de barras (más ancha)
        chart_card = Card(chart_row, title="Ingresos por período")
        chart_card.pack(side="left", fill="both", expand=True, padx=(0, 12))

        # Botones de período
        period_row = tk.Frame(chart_card.head, bg=C["card"])
        period_row.pack(side="right")
        for label, val in [("Hoy", "day"), ("Semana", "week"), ("Mes", "month")]:
            btn = tk.Radiobutton(period_row, text=label, variable=self.stats_mode, value=val,
                                 indicatoron=False,
                                 bg=C["card"], fg=C["text_2"],
                                 selectcolor=C["green_lt"],
                                 activebackground=C["green_lt"], activeforeground=C["green_2"],
                                 font=("Segoe UI", 9), cursor="hand2",
                                 borderwidth=1, relief="flat",
                                 padx=12, pady=4,
                                 command=lambda: threading.Thread(target=self._load_stats, daemon=True).start())
            btn.pack(side="left", padx=2)

        self._bar_chart = BarChart(chart_card.body, height=260)
        self._bar_chart.pack(fill="both", expand=True)

        # Dona de productos top
        donut_card = Card(chart_row, title="Top productos vendidos")
        donut_card.pack(side="right", fill="both", padx=(12, 0))
        donut_card.config(width=380)
        donut_card.pack_propagate(False)
        self._donut = DonutChart(donut_card.body, width=380, height=260)
        self._donut.pack(fill="both", expand=True)

        # === ÚLTIMAS VENTAS (tabla) ===
        recent_card = Card(scroll, title="Últimas ventas")
        recent_card.pack(fill="both", expand=True, padx=24, pady=(12, 24))

        cols = ("Fecha", "Producto", "Categoría", "Máquina", "Monto", "Estado")
        widths = {"Fecha": 140, "Producto": 220, "Categoría": 160,
                  "Máquina": 140, "Monto": 90, "Estado": 100}
        tree_frame = tk.Frame(recent_card.body, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)
        self._dash_tree = ModernTree(tree_frame, cols, widths, height=8)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._dash_tree.yview)
        self._dash_tree.configure(yscrollcommand=vsb.set)
        self._dash_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _make_scrollable(self, parent):
        """Crea un canvas scrollable y devuelve el frame interno."""
        canvas = tk.Canvas(parent, bg=C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel
        def on_mw(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", on_mw)

        return inner

    # ══════════════════════════════════════════════════
    #  MÁQUINAS
    # ══════════════════════════════════════════════════
    def _build_machines(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["mach"] = f

        card = Card(f, title="Equipos registrados")
        card.pack(fill="both", expand=True, padx=24, pady=20)

        self._mach_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"],
                                    font=("Segoe UI", 10))
        self._mach_count.pack(side="left", padx=12)

        SoftButton(card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_machines, daemon=True).start()
                   ).pack(side="right")

        cols = ("Código/SN", "Nombre", "Estado", "IP Interna", "IP Externa",
                "Versión SW", "Modelo", "Última sync")
        widths = {"Código/SN":140, "Nombre":140, "Estado":90,
                  "IP Interna":120, "IP Externa":130, "Versión SW":90,
                  "Modelo":160, "Última sync":140}
        tree_frame = tk.Frame(card.body, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)
        self._mach_tree = ModernTree(tree_frame, cols, widths)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._mach_tree.yview)
        self._mach_tree.configure(yscrollcommand=vsb.set)
        self._mach_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._mach_tree.bind("<<TreeviewSelect>>", self._on_mach_select)
        self._mach_tree.bind("<Double-1>", lambda e: self.sidebar.set_active("ctrl") or self._show_tab("ctrl"))

        tk.Label(card.body, text="↑ Doble clic para ir al panel de Control",
                 bg=C["card"], fg=C["muted"], font=("Segoe UI", 9)).pack(pady=(8, 0))

    # ══════════════════════════════════════════════════
    #  CONTROL
    # ══════════════════════════════════════════════════
    def _build_control(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["ctrl"] = f

        # Header card con info de máquina
        info = Card(f)
        info.pack(fill="x", padx=24, pady=(20, 12))

        info_row = tk.Frame(info.body, bg=C["card"])
        info_row.pack(fill="x")

        # Icono grande
        icon_canvas = tk.Canvas(info_row, width=64, height=64, bg=C["card"], highlightthickness=0)
        icon_canvas.pack(side="left")
        icon_canvas.create_oval(4, 4, 60, 60, fill=C["green_lt"], outline="")
        icon_canvas.create_text(32, 32, text="🏪", font=("Segoe UI Emoji", 22))

        name_f = tk.Frame(info_row, bg=C["card"])
        name_f.pack(side="left", padx=14)
        self._ctrl_name = tk.StringVar(value="Selecciona una máquina")
        self._ctrl_meta = tk.StringVar(value="Ve a 'Máquinas' y haz doble clic en una")
        tk.Label(name_f, textvariable=self._ctrl_name, bg=C["card"], fg=C["text"],
                 font=("Segoe UI Semibold", 16)).pack(anchor="w")
        tk.Label(name_f, textvariable=self._ctrl_meta, bg=C["card"], fg=C["muted"],
                 font=("Segoe UI", 10)).pack(anchor="w")

        self._ctrl_status_canvas = tk.Canvas(info_row, width=110, height=28, bg=C["card"], highlightthickness=0)
        self._ctrl_status_canvas.pack(side="right", padx=12, pady=20)

        # Grid de info técnica
        grid_card = Card(f)
        grid_card.pack(fill="x", padx=24, pady=(0, 12))
        grid = tk.Frame(grid_card.body, bg=C["card"])
        grid.pack(fill="x")
        self._ctrl_vars = {}
        for i, (key, lbl, icon) in enumerate([
            ("ip1", "IP Interna", "🌐"),
            ("ip2", "IP Externa", "🌍"),
            ("ver", "Versión SW", "💿"),
            ("sync", "Última sync", "🕐"),
        ]):
            col = tk.Frame(grid, bg=C["card"])
            col.grid(row=0, column=i, padx=18, pady=10, sticky="w")
            grid.columnconfigure(i, weight=1)
            tk.Label(col, text=f"{icon}  {lbl.upper()}", bg=C["card"], fg=C["label"],
                     font=("Segoe UI Semibold", 8)).pack(anchor="w")
            var = tk.StringVar(value="—")
            self._ctrl_vars[key] = var
            tk.Label(col, textvariable=var, bg=C["card"], fg=C["text"],
                     font=("Consolas", 12, "bold")).pack(anchor="w")

        # Layout: comandos a la izq, estado a la derecha
        bottom = tk.Frame(f, bg=C["bg"])
        bottom.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        # === COMANDOS ===
        cmd_card = Card(bottom, title="Comandos disponibles")
        cmd_card.pack(side="left", fill="both", expand=True, padx=(0, 12))

        # Servicio
        tk.Label(cmd_card.body, text="CONTROL DE SERVICIO", bg=C["card"], fg=C["label"],
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 6))
        svc_row = tk.Frame(cmd_card.body, bg=C["card"])
        svc_row.pack(fill="x", pady=(0, 14))
        for ctrl, label in [("0100", "Normal Service"), ("0101", "Out of Service")]:
            _, icon, dangerous, color = CMDS[ctrl]
            self._make_cmd_btn(svc_row, ctrl, label, icon, color, dangerous).pack(
                side="left", fill="x", expand=True, padx=4)

        # Sistema
        tk.Label(cmd_card.body, text="SISTEMA", bg=C["card"], fg=C["label"],
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 6))
        sys_grid = tk.Frame(cmd_card.body, bg=C["card"])
        sys_grid.pack(fill="x")
        cmds = [("0302", "Reboot"), ("0301", "Shutdown"),
                ("0307", "Restart SW"), ("0401", "Upgrade")]
        for i, (ctrl, label) in enumerate(cmds):
            _, icon, dangerous, color = CMDS[ctrl]
            r, c = i // 2, i % 2
            self._make_cmd_btn(sys_grid, ctrl, label, icon, color, dangerous).grid(
                row=r, column=c, padx=4, pady=4, sticky="ew")
            sys_grid.columnconfigure(c, weight=1)

        # === ESTADO ===
        stat_card = Card(bottom, title="Estado de componentes")
        stat_card.pack(side="right", fill="both", padx=(12, 0))
        stat_card.config(width=320)
        stat_card.pack_propagate(False)
        SoftButton(stat_card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_mach_status, daemon=True).start()
                   ).pack(side="right")
        self._status_txt = scrolledtext.ScrolledText(
            stat_card.body, bg="#f9fafb", fg=C["text"], font=("Consolas", 10),
            relief="flat", state="disabled", padx=10, pady=8, wrap="none")
        self._status_txt.pack(fill="both", expand=True)
        self._status_txt.tag_configure("ok",  foreground=C["green_2"])
        self._status_txt.tag_configure("err", foreground=C["red"])
        self._status_txt.tag_configure("key", foreground=C["muted"])
        self._status_txt.tag_configure("val", foreground=C["text"], font=("Consolas", 10, "bold"))

    def _make_cmd_btn(self, parent, ctrl, label, icon, color, dangerous):
        # Tarjeta-botón
        btn = tk.Frame(parent, bg="#f9fafb", highlightthickness=1,
                       highlightbackground=C["card_border"], cursor="hand2")
        inner = tk.Frame(btn, bg="#f9fafb")
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        ic = tk.Label(inner, text=icon, bg="#f9fafb", font=("Segoe UI Emoji", 18))
        ic.pack(side="left", padx=(0, 10))
        tx = tk.Label(inner, text=label, bg="#f9fafb", fg=C["text"],
                      font=("Segoe UI Semibold", 11))
        tx.pack(side="left")
        for w in (btn, inner, ic, tx):
            w.bind("<Button-1>", lambda e: self._send_cmd(ctrl, label, dangerous))
            w.bind("<Enter>", lambda e: [
                btn.config(highlightbackground=color, bg=color+"15"),
                inner.config(bg=color+"15"),
                ic.config(bg=color+"15"),
                tx.config(bg=color+"15", fg=color),
            ])
            w.bind("<Leave>", lambda e: [
                btn.config(highlightbackground=C["card_border"], bg="#f9fafb"),
                inner.config(bg="#f9fafb"),
                ic.config(bg="#f9fafb"),
                tx.config(bg="#f9fafb", fg=C["text"]),
            ])
        return btn

    # ══════════════════════════════════════════════════
    #  PEDIDOS
    # ══════════════════════════════════════════════════
    def _build_orders(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["ord"] = f

        card = Card(f, title="Historial completo de pedidos")
        card.pack(fill="both", expand=True, padx=24, pady=20)

        self._ord_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"],
                                   font=("Segoe UI", 10))
        self._ord_count.pack(side="left", padx=12)

        SoftButton(card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_orders, daemon=True).start()
                   ).pack(side="right")

        cols = ("Folio", "Producto", "Categoría", "Máquina", "Monto", "Cant.", "Fecha", "Estado")
        widths = {"Folio":150, "Producto":210, "Categoría":150,
                  "Máquina":140, "Monto":85, "Cant.":50, "Fecha":140, "Estado":100}
        tree_frame = tk.Frame(card.body, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)
        self._ord_tree = ModernTree(tree_frame, cols, widths)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._ord_tree.yview)
        self._ord_tree.configure(yscrollcommand=vsb.set)
        self._ord_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ══════════════════════════════════════════════════
    #  ARTÍCULOS VENDIDOS
    # ══════════════════════════════════════════════════
    def _build_items(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["items"] = f

        # Filtro de período (como tabs)
        filter_bar = tk.Frame(f, bg=C["bg"])
        filter_bar.pack(fill="x", padx=24, pady=(20, 0))
        tk.Label(filter_bar, text="Período:", bg=C["bg"], fg=C["text_2"],
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=(0, 12))

        self._items_mode = tk.StringVar(value="all")
        for label, val in [("Todo", "all"), ("Hoy", "today"),
                            ("Esta semana", "week"), ("Este mes", "month")]:
            btn = tk.Radiobutton(filter_bar, text=label, variable=self._items_mode, value=val,
                                 indicatoron=False,
                                 bg=C["card"], fg=C["text_2"],
                                 selectcolor=C["green_lt"],
                                 activebackground=C["green_lt"], activeforeground=C["green_2"],
                                 font=("Segoe UI", 10), cursor="hand2",
                                 borderwidth=1, relief="solid",
                                 padx=14, pady=6,
                                 command=self._render_items)
            btn.pack(side="left", padx=2)

        SoftButton(filter_bar, "↻  Actualizar", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_orders, daemon=True).start()
                   ).pack(side="right")

        # Resumen agrupado
        sum_card = Card(f, title="Resumen por artículo")
        sum_card.pack(fill="x", padx=24, pady=(16, 12))
        self._items_count = tk.Label(sum_card.head, text="", bg=C["card"], fg=C["muted"],
                                     font=("Segoe UI", 10))
        self._items_count.pack(side="left", padx=12)

        cols_sum = ("Artículo", "Categoría", "Cant. vendida", "Ingresos", "% del total")
        widths_sum = {"Artículo":250, "Categoría":160, "Cant. vendida":110,
                      "Ingresos":110, "% del total":100}
        tree_sum_frame = tk.Frame(sum_card.body, bg=C["card"])
        tree_sum_frame.pack(fill="both", expand=True)
        self._items_sum_tree = ModernTree(tree_sum_frame, cols_sum, widths_sum, height=6)
        vsb1 = ttk.Scrollbar(tree_sum_frame, orient="vertical", command=self._items_sum_tree.yview)
        self._items_sum_tree.configure(yscrollcommand=vsb1.set)
        self._items_sum_tree.pack(side="left", fill="both", expand=True)
        vsb1.pack(side="right", fill="y")

        # Detalle
        det_card = Card(f, title="Detalle de ventas")
        det_card.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self._items_det_count = tk.Label(det_card.head, text="", bg=C["card"], fg=C["muted"],
                                         font=("Segoe UI", 10))
        self._items_det_count.pack(side="left", padx=12)

        cols_det = ("Artículo", "Categoría", "Precio", "Máquina", "Fecha", "Estado")
        widths_det = {"Artículo":230, "Categoría":160, "Precio":85,
                      "Máquina":140, "Fecha":140, "Estado":100}
        tree_det_frame = tk.Frame(det_card.body, bg=C["card"])
        tree_det_frame.pack(fill="both", expand=True)
        self._items_det_tree = ModernTree(tree_det_frame, cols_det, widths_det)
        vsb2 = ttk.Scrollbar(tree_det_frame, orient="vertical", command=self._items_det_tree.yview)
        self._items_det_tree.configure(yscrollcommand=vsb2.set)
        self._items_det_tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")

    # ══════════════════════════════════════════════════
    #  CATÁLOGO
    # ══════════════════════════════════════════════════
    def _build_products(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["prod"] = f

        card = Card(f, title="Catálogo de productos")
        card.pack(fill="both", expand=True, padx=24, pady=20)

        self._prod_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"],
                                    font=("Segoe UI", 10))
        self._prod_count.pack(side="left", padx=12)
        SoftButton(card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_products, daemon=True).start()
                   ).pack(side="right")

        cols = ("ID", "Nombre", "Precio", "Tipo", "Stock", "Estado")
        widths = {"ID":80, "Nombre":240, "Precio":90, "Tipo":160, "Stock":80, "Estado":90}
        tree_frame = tk.Frame(card.body, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)
        self._prod_tree = ModernTree(tree_frame, cols, widths)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._prod_tree.yview)
        self._prod_tree.configure(yscrollcommand=vsb.set)
        self._prod_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ══════════════════════════════════════════════════
    #  REABASTECIMIENTO
    # ══════════════════════════════════════════════════
    def _build_replenishment(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["rep"] = f

        card = Card(f, title="Registro de reabastecimiento")
        card.pack(fill="both", expand=True, padx=24, pady=20)

        self._rep_count = tk.Label(card.head, text="", bg=C["card"], fg=C["muted"],
                                   font=("Segoe UI", 10))
        self._rep_count.pack(side="left", padx=12)
        SoftButton(card.head, "↻", color=C["green"], kind="ghost",
                   command=lambda: threading.Thread(target=self._load_rep, daemon=True).start()
                   ).pack(side="right")

        cols = ("Fecha", "Máquina", "Artículo", "Cantidad", "Operador")
        widths = {"Fecha":140, "Máquina":140, "Artículo":240, "Cantidad":90, "Operador":140}
        tree_frame = tk.Frame(card.body, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)
        self._rep_tree = ModernTree(tree_frame, cols, widths)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._rep_tree.yview)
        self._rep_tree.configure(yscrollcommand=vsb.set)
        self._rep_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ══════════════════════════════════════════════════
    #  LOG
    # ══════════════════════════════════════════════════
    def _build_log(self):
        f = tk.Frame(self.body, bg=C["bg"])
        self._tab_frames["log"] = f

        card = Card(f, title="Registro de actividad")
        card.pack(fill="both", expand=True, padx=24, pady=20)

        SoftButton(card.head, "🗑  Limpiar", color=C["red"], kind="ghost",
                   command=lambda: (self._log_txt.config(state="normal"),
                                    self._log_txt.delete("1.0", "end"),
                                    self._log_txt.config(state="disabled"))
                   ).pack(side="right")

        self._log_txt = scrolledtext.ScrolledText(
            card.body, bg="#f9fafb", fg=C["text"], font=("Consolas", 10),
            relief="flat", state="disabled", padx=12, pady=10)
        self._log_txt.pack(fill="both", expand=True)
        self._log_txt.tag_configure("ok",  foreground=C["green_2"])
        self._log_txt.tag_configure("er",  foreground=C["red"])
        self._log_txt.tag_configure("in",  foreground=C["blue"])
        self._log_txt.tag_configure("wr",  foreground=C["amber"])
        self._log_txt.tag_configure("ts",  foreground=C["purple"])

    # ══════════════════════════════════════════════════
    #  CARGA DE DATOS
    # ══════════════════════════════════════════════════
    def _load_all(self):
        self._log("Iniciando carga completa...", "in")
        test = self.client.req("GET", "/api/terminal?page=0&size=1")
        if isinstance(test, dict) and test.get("error") == "TOKEN_EXPIRED":
            self._log("⚠ Token expirado", "er")
            self._draw_conn_badge(False)
            return
        if isinstance(test, dict) and "error" in test:
            self._log(f"Error de conexión: {test.get('error')}", "er")
            self._draw_conn_badge(False)
            return
        self._draw_conn_badge(True)

        def safe_run(name, fn):
            try: fn()
            except Exception as e: self._log(f"Error en {name}: {e}", "er")

        threads = [
            threading.Thread(target=safe_run, args=("stats", self._load_stats), daemon=True),
            threading.Thread(target=safe_run, args=("machines", self._load_machines), daemon=True),
            threading.Thread(target=safe_run, args=("orders", self._load_orders), daemon=True),
            threading.Thread(target=safe_run, args=("products", self._load_products), daemon=True),
            threading.Thread(target=safe_run, args=("rep", self._load_rep), daemon=True),
        ]
        for t in threads: t.start()
        self.root.after(0, lambda: self._upd_lbl.config(
            text="Última sync: " + datetime.now().strftime("%H:%M:%S")))

    def _load_stats(self):
        mode = self.stats_mode.get()
        summary, chart, periods = self.client.get_stats(mode)
        self.root.after(0, lambda: self._apply_stats(summary, chart, periods, mode))

    def _apply_stats(self, summary, chart, periods, mode):
        if isinstance(summary, dict) and "data" in summary and isinstance(summary["data"], list):
            data = summary["data"]
            today = data[0] if len(data) > 0 else {}
            month = data[1] if len(data) > 1 else {}
            rev_d = int(float(today.get("saleAmount", 0) or 0))
            cnt_d = int(today.get("saleCount", 0) or 0)
            rev_m = int(float(month.get("saleAmount", 0) or 0))
            cnt_m = int(month.get("saleCount", 0) or 0)
            self._sc["rev_day"].set(f"${rev_d:,}")
            self._sc["cnt_day"].set(str(cnt_d))
            self._sc["cnt_month"].set(str(cnt_m), f"{cnt_m} ventas")
            self._sc["rev_month"].set(f"${rev_m:,}", "MXN")
            on = len([m for m in self.machines if m.get("status") in (True, 1)])
            self._sc["online"].set(str(on) if self.machines else "—",
                                   f"de {len(self.machines)}" if self.machines else "")
            self._draw_conn_badge(True)
            self._log(f"Stats OK: hoy={cnt_d} (${rev_d}) | mes={cnt_m} (${rev_m:,})", "ok")

        # Gráfica de barras
        if isinstance(chart, dict) and "data" in chart and isinstance(chart["data"], list):
            cdata = chart["data"]
            vals = [float(d.get("saleAmount", 0) or 0) for d in cdata]
            if mode == "day":
                lbls = ["Hoy"]; color = C["bar_a"]
            elif mode == "week":
                lbls = [(datetime.now(TZ) - timedelta(days=6-i)).strftime("%a %d")
                        for i in range(len(periods))]
                color = C["bar_b"]
            else:
                lbls = ["Este mes"]; color = C["bar_d"]
            self._bar_chart.set_data(vals, lbls, color)

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
            ts = m.get("terminalStatus") or {}
            is_on = m.get("status") in (True, 1)
            if is_on: on += 1
            self._mach_tree.add_row((
                m.get("code", "—"),
                m.get("name", "—"),
                "● Online" if is_on else "● Offline",
                ts.get("intranetIp", "—"),
                ts.get("internetIp", "—"),
                ts.get("curVersion", "—"),
                m.get("terminalModelCode", "—"),
                (ts.get("lastUpdateTime", "—") or "—")[:16],
            ), tags=("online" if is_on else "offline",))
        self._mach_count.config(text=f"{len(lst)} equipos · {on} online")

    def _on_mach_select(self, _event):
        sel = self._mach_tree.selection()
        if not sel: return
        vals = self._mach_tree.item(sel[0], "values")
        code = vals[0] if vals else ""
        m = next((x for x in self.machines if x.get("code") == code), None)
        if not m: return
        self.sel_mach = m
        ts = m.get("terminalStatus") or {}
        is_on = m.get("status") in (True, 1)
        self._ctrl_name.set(m.get("name") or m.get("code") or "—")
        self._ctrl_meta.set(f"SN: {m.get('code','—')} · {m.get('terminalModelCode','—')}")

        # Badge de estado
        c = self._ctrl_status_canvas
        c.delete("all")
        bg = C["green_lt"] if is_on else C["red_lt"]
        fg = C["green_2"] if is_on else C["red"]
        text = "● Online" if is_on else "● Offline"
        c.create_rectangle(0, 4, 110, 24, fill=bg, outline="", width=0)
        c.create_text(55, 14, text=text, fill=fg, font=("Segoe UI Semibold", 9))

        self._ctrl_vars["ip1"].set(ts.get("intranetIp", "—"))
        self._ctrl_vars["ip2"].set(ts.get("internetIp", "—"))
        self._ctrl_vars["ver"].set(ts.get("curVersion", "—"))
        self._ctrl_vars["sync"].set((ts.get("lastUpdateTime", "—") or "—")[:16])
        threading.Thread(target=self._load_mach_status, daemon=True).start()

    def _load_mach_status(self):
        if not self.sel_mach: return
        d = self.client.get_machine_status(self.sel_mach.get("code", ""))
        lst = (d or {}).get("content") or (d or {}).get("list") or []
        self.root.after(0, lambda: self._render_status(lst))

    def _render_status(self, lst):
        self._status_txt.config(state="normal")
        self._status_txt.delete("1.0", "end")
        m = self.sel_mach or {}
        ts = m.get("terminalStatus") or {}
        if lst:
            for c in lst[:15]:
                ok = c.get("status") in (1, True, "normal")
                nm = c.get("compType") or c.get("name", "—")
                self._status_txt.insert("end", f"  {nm:<26}", "key")
                self._status_txt.insert("end", ("✓ OK\n" if ok else "✗ Error\n"),
                                        ("ok" if ok else "err"))
        else:
            for k, v in [("Estado", "Online" if m.get("status") in (True, 1) else "Offline"),
                         ("IP Interna", ts.get("intranetIp", "—")),
                         ("IP Externa", ts.get("internetIp", "—")),
                         ("Versión SW", ts.get("curVersion", "—")),
                         ("Run Mode", ts.get("runMode", "—")),
                         ("Última sync", (ts.get("lastUpdateTime", "—") or "—")[:16])]:
                self._status_txt.insert("end", f"  {k:<14}", "key")
                self._status_txt.insert("end", f"{v}\n", "val")
        self._status_txt.config(state="disabled")

    def _send_cmd(self, ctrl, label, dangerous):
        if not self.sel_mach:
            messagebox.showwarning("Sin selección", "Selecciona una máquina primero.")
            return
        if dangerous:
            nm = self.sel_mach.get("name") or self.sel_mach.get("code", "")
            if not messagebox.askyesno("Confirmar", f"¿Ejecutar '{label}' en {nm}?"):
                return
        threading.Thread(target=self._exec_cmd, args=(ctrl, label), daemon=True).start()

    def _exec_cmd(self, ctrl, label):
        code = self.sel_mach.get("code", "")
        self._log(f"→ devCommand {{terminalCode:{code}, control:{ctrl}}} [{label}]", "in")
        d = self.client.send_command(code, ctrl)
        if d and isinstance(d, dict) and "error" not in d:
            self._log(f"✓ {label} ejecutado correctamente", "ok")
            self.root.after(0, lambda: messagebox.showinfo("✅ Éxito",
                                                           f"'{label}' ejecutado en {code}"))
        else:
            self._log(f"⚠ {label}: {d}", "wr")

    def _load_orders(self):
        d = self.client.get_orders()
        if not d or "error" in d:
            self._log(f"Error pedidos: {d}", "er"); return
        lst = d.get("content") or d.get("list") or []
        self.orders = lst
        self.root.after(0, lambda: self._render_orders(lst))
        self.root.after(0, self._render_items)
        self.root.after(0, self._render_dash_recent)
        self.root.after(0, self._render_donut)

    def _render_orders(self, lst):
        self._ord_tree.clear()
        for o in lst:
            det = (o.get("commodityOrderDetailDtos") or [{}])[0]
            succ = det.get("successNum", 0) or 0
            fail = det.get("failureNum", 0) or 0
            state = "Entregado" if succ > 0 else ("Fallo" if fail > 0 else "Pendiente")
            tag = "delivered" if succ > 0 else ("fail" if fail > 0 else "pending")
            self._ord_tree.add_row((
                (o.get("id", "") or "")[:18],
                det.get("goodsName", "—"),
                det.get("goodsTypeName", "—"),
                o.get("terminalCode", "—"),
                f"${float(o.get('totalAmount',0)):.2f}",
                det.get("orderNum", "—"),
                (o.get("createDate", "—") or "—")[:16],
                state,
            ), tags=(tag,))
        self._ord_count.config(text=f"{len(lst)} pedidos")
        self._log(f"{len(lst)} pedidos cargados", "ok")

    def _render_dash_recent(self):
        """Últimas ventas en el dashboard — solo ENTREGADOS."""
        self._dash_tree.clear()
        delivered = [o for o in self.orders
                     if ((o.get("commodityOrderDetailDtos") or [{}])[0]).get("successNum", 0) > 0]
        for o in delivered[:15]:
            det = (o.get("commodityOrderDetailDtos") or [{}])[0]
            self._dash_tree.add_row((
                (o.get("createDate", "—") or "—")[:16],
                det.get("goodsName", "—"),
                det.get("goodsTypeName", "—"),
                o.get("terminalCode", "—"),
                f"${float(o.get('totalAmount',0)):.2f}",
                "Entregado",
            ), tags=("delivered",))

    def _render_donut(self):
        """Top productos en dona del dashboard — solo ENTREGADOS."""
        from collections import Counter
        counts = Counter()
        for o in self.orders:
            det = (o.get("commodityOrderDetailDtos") or [{}])[0]
            if (det.get("successNum", 0) or 0) > 0:
                name = det.get("goodsName", "—")
                qty = int(det.get("orderNum", 1) or 1)
                counts[name] += qty

        top = counts.most_common(5)
        colors = [C["green"], C["blue"], C["amber"], C["purple"], C["pink"]]
        data = [(name, qty, colors[i % len(colors)]) for i, (name, qty) in enumerate(top)]
        self._donut.set_data(data)

    def _render_items(self):
        if not hasattr(self, "_items_sum_tree"): return
        now_tz = datetime.now(TZ)
        today_date = now_tz.date()
        mode = self._items_mode.get()
        items = []

        for o in self.orders:
            raw_date = o.get("createDate", "") or ""
            try:
                dt = datetime.strptime(raw_date[:16], "%Y-%m-%d %H:%M")
                dt_date = dt.date()
            except:
                dt = None; dt_date = None

            if dt_date and mode != "all":
                if mode == "today":
                    if dt_date != today_date: continue
                elif mode == "week":
                    diff = (today_date - dt_date).days
                    if diff < 0 or diff > 6: continue
                elif mode == "month":
                    if dt_date.year != today_date.year or dt_date.month != today_date.month:
                        continue

            det = (o.get("commodityOrderDetailDtos") or [{}])[0]
            if not det.get("goodsName"): continue
            succ = det.get("successNum", 0) or 0
            fail = det.get("failureNum", 0) or 0
            state = "Entregado" if succ > 0 else ("Fallo" if fail > 0 else "Pendiente")
            # SOLO ventas reales
            if state != "Entregado": continue

            items.append({
                "name": det.get("goodsName", "—"),
                "category": det.get("goodsTypeName", "—"),
                "amount": float(o.get("totalAmount", 0) or 0),
                "price": float(det.get("singleAmount", 0) or 0),
                "qty": int(det.get("orderNum", 1) or 1),
                "machine": o.get("terminalCode", "—"),
                "date": (o.get("createDate", "—") or "—")[:16],
                "state": state,
            })

        # Resumen
        summary = {}
        total_rev = sum(i["amount"] for i in items)
        for it in items:
            k = it["name"]
            if k not in summary:
                summary[k] = {"name": k, "category": it["category"], "qty": 0, "rev": 0.0}
            summary[k]["qty"] += it["qty"]
            summary[k]["rev"] += it["amount"]

        self._items_sum_tree.clear()
        for s in sorted(summary.values(), key=lambda x: -x["rev"]):
            pct = f"{(s['rev']/total_rev*100):.1f}%" if total_rev > 0 else "—"
            self._items_sum_tree.add_row((
                s["name"], s["category"],
                str(s["qty"]), f"${s['rev']:.2f}", pct,
            ))
        self._items_count.config(
            text=f"{len(summary)} artículos distintos · {len(items)} ventas · ${total_rev:,.2f} total")

        self._items_det_tree.clear()
        for it in items:
            self._items_det_tree.add_row((
                it["name"], it["category"],
                f"${it['price']:.2f}", it["machine"],
                it["date"], it["state"],
            ), tags=("delivered",))
        self._items_det_count.config(text=f"{len(items)} ventas en este período")

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
            st = "Activo" if p.get("status") in (True, 1) else "Inactivo"
            tag = "delivered" if p.get("status") in (True, 1) else "fail"
            self._prod_tree.add_row((
                p.get("id", "—"),
                p.get("name") or p.get("goodsName", "—"),
                f"${p.get('price') or p.get('sellPrice',0)}",
                p.get("goodsTypeName") or p.get("typeName", "—"),
                p.get("stock", "—"),
                st,
            ), tags=(tag,))
        self._prod_count.config(text=f"{len(lst)} productos")

    def _load_rep(self):
        d = self.client.get_replenishment()
        if not d or (isinstance(d, dict) and ("error" in d or d.get("status") == 400)):
            self.root.after(0, lambda: self._render_rep([]))
            return
        lst = d.get("content") or d.get("list") or []
        self.rep = lst
        self.root.after(0, lambda: self._render_rep(lst))

    def _render_rep(self, lst):
        self._rep_tree.clear()
        for r in lst:
            self._rep_tree.add_row((
                (r.get("createTime", "—") or "—")[:16],
                r.get("terminalCode", "—"),
                r.get("goodsName") or r.get("productName", "—"),
                r.get("count") or r.get("quantity", "—"),
                r.get("operName") or r.get("operator", "—"),
            ))
        self._rep_count.config(text=f"{len(lst)} registros")

    def _log(self, msg, tag="in"):
        def _do():
            if not hasattr(self, "_log_txt"): return
            self._log_txt.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_txt.insert("end", f"[{ts}] ", "ts")
            self._log_txt.insert("end", msg + "\n", tag)
            self._log_txt.see("end")
            self._log_txt.config(state="disabled")
        self.root.after(0, _do)

    def _start_auto_refresh(self):
        def loop():
            while self.auto_refresh:
                time.sleep(60)
                if self.auto_refresh:
                    self._log("Auto-refresh...", "in")
                    threading.Thread(target=self._load_all, daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import traceback
    try:
        token = load_token_from_file()
        if not token:
            messagebox.showerror("Sin token",
                f"No se encontró el archivo token.txt en:\n{SCRIPT_DIR}\n\n"
                "1. Inicia sesión en a.vmc002.csmology.com\n"
                "2. Abre la consola (F12) y pega:\n"
                "   copy(document.querySelector('#app').__vue__.$store.state.user.token)\n"
                "3. Pega el resultado en token.txt y vuelve a abrir la app.")
            sys.exit(1)

        with _token_lock:
            _current_token["value"] = token

        root = tk.Tk()
        # Aplicar escalado de Tk acorde al DPI del sistema
        # tk.scaling es la cantidad de pixeles por punto (default 1.333 = 96 DPI)
        try:
            root.tk.call("tk", "scaling", DPI_SCALE * 1.333)
        except Exception:
            pass
        app = VMCDesktop(root)

        def on_close():
            app.auto_refresh = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

    except Exception as e:
        err = traceback.format_exc()
        try:
            with open(os.path.join(SCRIPT_DIR, "error.log"), "w", encoding="utf-8") as f:
                f.write(err)
        except: pass
        try:
            err_root = tk.Tk()
            err_root.title("VMC Control - Error")
            err_root.geometry("720x520")
            err_root.configure(bg="#f4f6fa")
            tk.Label(err_root, text="Error al iniciar la aplicación",
                     bg="#f4f6fa", fg="#ef4444",
                     font=("Segoe UI", 14, "bold")).pack(pady=14)
            txt = scrolledtext.ScrolledText(err_root, bg="#ffffff", fg="#1f2937",
                                             font=("Consolas", 9), wrap="word")
            txt.pack(fill="both", expand=True, padx=18, pady=8)
            txt.insert("1.0", err)
            txt.config(state="disabled")
            tk.Button(err_root, text="Cerrar", command=err_root.destroy,
                      bg="#ef4444", fg="white", font=("Segoe UI", 10, "bold"),
                      relief="flat", padx=20, pady=6).pack(pady=12)
            err_root.mainloop()
        except: print(err)
        sys.exit(1)
