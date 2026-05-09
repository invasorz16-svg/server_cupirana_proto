"""
VMC Control Center — Servidor Local (Fase 2)
=============================================
Reemplaza el servidor csmology.com con un servidor FastAPI local.
Corre en tu PC Windows y se comunica con la máquina por WiFi.

Uso:
    python vmc_server.py

El servidor arranca en http://0.0.0.0:8080
Dashboard en http://localhost:8080/docs (Swagger UI)
"""

import os
import sys
import json
import uuid
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vmc_data.db")
HOST = "0.0.0.0"
PORT = 8080
TZ_OFFSET = timezone(timedelta(hours=-6))  # CST México

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("VMC-Server")


# ─────────────────────────────────────────────
# Base de datos SQLite
# ─────────────────────────────────────────────

def now_local() -> str:
    """Timestamp actual en zona horaria de México."""
    return datetime.now(TZ_OFFSET).isoformat()


def init_db():
    """Crear tablas si no existen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            price       REAL NOT NULL DEFAULT 0,
            slot        TEXT NOT NULL,
            image       TEXT DEFAULT '',
            stock       INTEGER DEFAULT 10,
            active      INTEGER DEFAULT 1,
            category    TEXT DEFAULT '',
            created_at  TEXT DEFAULT '',
            updated_at  TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id      INTEGER,
            product_name    TEXT NOT NULL,
            amount          REAL NOT NULL,
            slot            TEXT DEFAULT '',
            payment_type    TEXT DEFAULT 'cash',
            machine_code    TEXT DEFAULT 'BC8A08520A50',
            status          TEXT DEFAULT 'success',
            error_detail    TEXT DEFAULT '',
            created_at      TEXT NOT NULL,
            synced          INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS machine_status (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            online      INTEGER DEFAULT 1,
            ip_address  TEXT DEFAULT '',
            sw_version  TEXT DEFAULT '',
            uptime_sec  INTEGER DEFAULT 0,
            last_error  TEXT DEFAULT '',
            slot_status TEXT DEFAULT '',
            timestamp   TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL,
            slot        TEXT NOT NULL,
            quantity    INTEGER DEFAULT 0,
            max_qty     INTEGER DEFAULT 10,
            last_refill TEXT DEFAULT '',
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            type      TEXT NOT NULL,
            source    TEXT DEFAULT 'server',
            message   TEXT DEFAULT '',
            data      TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        )
    """)

    # Índices para consultas frecuentes
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(type)")

    # Insertar configuración por defecto si no existe
    defaults = {
        "machine_code": "BC8A08520A50",
        "machine_name": "M02-UK-BC8A",
        "currency": "MXN",
        "timezone": "America/Mexico_City",
        "heartbeat_interval": "30",
        "cart_limit": "3",
        "language": "es",
        "offline_mode": "0",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # Productos iniciales (los reales de la máquina) si la tabla está vacía
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        productos = [
            ("Paquete sorpresa 3", 40.0, "A1", "", 10, "Paquetes"),
            ("Micas para Pokemon", 120.0, "A2", "", 10, "Accesorios"),
            ("Paquete Sorpresa 4", 40.0, "A3", "", 10, "Paquetes"),
            ("Paquetes random pokemon y Yugioh", 40.0, "A4", "", 10, "Paquetes"),
            ("Super Paquete Sorpresa", 400.0, "B1", "", 5, "Premium"),
            ("Paquete Sorpresa BASE", 250.0, "B2", "", 5, "Premium"),
            ("Tarjetas Pokemon", 40.0, "C1", "", 15, "Tarjetas"),
            ("Mica Yugi Oh", 120.0, "C2", "", 10, "Accesorios"),
            ("Mica Pokemon", 120.0, "C3", "", 10, "Accesorios"),
        ]
        ts = now_local()
        for name, price, slot, image, stock, cat in productos:
            c.execute(
                "INSERT INTO products (name, price, slot, image, stock, active, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (name, price, slot, image, stock, cat, ts, ts),
            )
        logger.info(f"Insertados {len(productos)} productos iniciales")

    conn.commit()
    conn.close()
    logger.info(f"Base de datos inicializada: {DB_PATH}")


def get_db():
    """Obtener conexión a la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────
# Modelos Pydantic
# ─────────────────────────────────────────────

class SaleCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: str
    amount: float
    slot: str = ""
    payment_type: str = "cash"
    machine_code: str = "BC8A08520A50"
    timestamp: Optional[str] = None

class SaleResult(BaseModel):
    sale_id: int
    status: str = "success"  # success | failed | timeout
    error_detail: str = ""

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    slot: Optional[str] = None
    image: Optional[str] = None
    stock: Optional[int] = None
    active: Optional[int] = None
    category: Optional[str] = None

class ProductCreate(BaseModel):
    name: str
    price: float
    slot: str
    image: str = ""
    stock: int = 10
    active: int = 1
    category: str = ""

class MachineStatusReport(BaseModel):
    online: int = 1
    ip_address: str = ""
    sw_version: str = ""
    uptime_sec: int = 0
    last_error: str = ""
    slot_status: str = ""

class MachineCommand(BaseModel):
    command: str  # reboot, update_products, disable_sales, enable_sales, test_motor
    params: Optional[dict] = None

class ConfigUpdate(BaseModel):
    key: str
    value: str

class InventoryUpdate(BaseModel):
    product_id: int
    slot: str
    quantity: int
    max_qty: int = 10


# ─────────────────────────────────────────────
# WebSocket Manager
# ─────────────────────────────────────────────

class ConnectionManager:
    """Gestiona conexiones WebSocket de máquinas y dashboards."""

    def __init__(self):
        self.machines: dict[str, WebSocket] = {}      # machine_code -> ws
        self.dashboards: list[WebSocket] = []          # dashboards conectados
        self.last_heartbeat: dict[str, str] = {}       # machine_code -> timestamp

    async def connect_machine(self, ws: WebSocket, machine_code: str):
        await ws.accept()
        self.machines[machine_code] = ws
        self.last_heartbeat[machine_code] = now_local()
        logger.info(f"Máquina conectada: {machine_code}")
        await self.broadcast_to_dashboards({
            "type": "machine_connected",
            "machine_code": machine_code,
            "timestamp": now_local()
        })

    async def connect_dashboard(self, ws: WebSocket):
        await ws.accept()
        self.dashboards.append(ws)
        logger.info(f"Dashboard conectado (total: {len(self.dashboards)})")

    def disconnect_machine(self, machine_code: str):
        self.machines.pop(machine_code, None)
        logger.info(f"Máquina desconectada: {machine_code}")

    def disconnect_dashboard(self, ws: WebSocket):
        if ws in self.dashboards:
            self.dashboards.remove(ws)
            logger.info(f"Dashboard desconectado (quedan: {len(self.dashboards)})")

    async def send_to_machine(self, machine_code: str, message: dict) -> bool:
        ws = self.machines.get(machine_code)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error enviando a máquina {machine_code}: {e}")
                self.disconnect_machine(machine_code)
        return False

    async def broadcast_to_dashboards(self, message: dict):
        dead = []
        for ws in self.dashboards:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_dashboard(ws)

    def is_machine_online(self, machine_code: str) -> bool:
        return machine_code in self.machines

    def get_status(self) -> dict:
        return {
            "machines_connected": list(self.machines.keys()),
            "dashboards_connected": len(self.dashboards),
            "last_heartbeats": self.last_heartbeat,
        }


manager = ConnectionManager()


# ─────────────────────────────────────────────
# App FastAPI
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"VMC Control Center arrancando en http://{HOST}:{PORT}")
    logger.info(f"Documentación API: http://localhost:{PORT}/docs")
    yield
    logger.info("VMC Control Center detenido")


app = FastAPI(
    title="VMC Control Center — Servidor Local",
    description="API REST + WebSocket para controlar máquinas expendedoras. Reemplaza csmology.com.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def log_event(event_type: str, message: str, source: str = "server", data: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO event_log (type, source, message, data, timestamp) VALUES (?, ?, ?, ?, ?)",
        (event_type, source, message, data, now_local()),
    )
    conn.commit()
    conn.close()


def row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row)


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# ENDPOINTS: Estado general
# ─────────────────────────────────────────────

@app.get("/", tags=["General"])
def root():
    """Estado del servidor."""
    return {
        "name": "VMC Control Center",
        "version": "2.0.0",
        "status": "running",
        "timestamp": now_local(),
        "connections": manager.get_status(),
    }


@app.get("/api/health", tags=["General"])
def health_check():
    return {"status": "ok", "timestamp": now_local()}


# ─────────────────────────────────────────────
# ENDPOINTS: Ventas
# ─────────────────────────────────────────────

@app.post("/api/sales", tags=["Ventas"])
async def create_sale(sale: SaleCreate):
    """
    Registrar una venta nueva (enviado desde la máquina).
    La máquina llama este endpoint cuando el cliente paga.
    """
    ts = sale.timestamp or now_local()
    conn = get_db()

    # Si viene product_id, verificar que existe
    if sale.product_id:
        prod = conn.execute("SELECT * FROM products WHERE id = ?", (sale.product_id,)).fetchone()
        if not prod:
            conn.close()
            raise HTTPException(404, "Producto no encontrado")

    cursor = conn.execute(
        "INSERT INTO sales (product_id, product_name, amount, slot, payment_type, machine_code, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (sale.product_id, sale.product_name, sale.amount, sale.slot,
         sale.payment_type, sale.machine_code, ts),
    )
    sale_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log_event("sale_created", f"Venta #{sale_id}: {sale.product_name} ${sale.amount}", "machine")

    # Notificar dashboards
    await manager.broadcast_to_dashboards({
        "type": "new_sale",
        "sale_id": sale_id,
        "product_name": sale.product_name,
        "amount": sale.amount,
        "slot": sale.slot,
        "payment_type": sale.payment_type,
        "timestamp": ts,
    })

    return {
        "status": "ok",
        "sale_id": sale_id,
        "action": "dispense",
        "slot": sale.slot,
        "message": "Dispensar producto",
    }


@app.post("/api/sales/{sale_id}/result", tags=["Ventas"])
async def report_sale_result(sale_id: int, result: SaleResult):
    """
    Reportar resultado del despacho (éxito/fallo).
    La máquina llama después de intentar despachar.
    """
    conn = get_db()
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if not sale:
        conn.close()
        raise HTTPException(404, "Venta no encontrada")

    conn.execute(
        "UPDATE sales SET status = ?, error_detail = ? WHERE id = ?",
        (result.status, result.error_detail, sale_id),
    )

    # Si éxito, decrementar stock
    if result.status == "success" and sale["product_id"]:
        conn.execute(
            "UPDATE products SET stock = MAX(0, stock - 1) WHERE id = ?",
            (sale["product_id"],),
        )

    conn.commit()
    conn.close()

    status_text = "exitoso" if result.status == "success" else f"fallido: {result.error_detail}"
    log_event("sale_result", f"Venta #{sale_id} despacho {status_text}", "machine")

    await manager.broadcast_to_dashboards({
        "type": "sale_result",
        "sale_id": sale_id,
        "status": result.status,
        "error_detail": result.error_detail,
        "timestamp": now_local(),
    })

    return {"status": "ok", "sale_id": sale_id, "recorded": result.status}


@app.get("/api/sales", tags=["Ventas"])
def get_sales(
    from_date: Optional[str] = Query(None, alias="from", description="Fecha inicio ISO"),
    to_date: Optional[str] = Query(None, alias="to", description="Fecha fin ISO"),
    status: Optional[str] = Query(None, description="Filtrar por status: success, failed, pending"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
):
    """Consultar historial de ventas con filtros opcionales."""
    conn = get_db()
    query = "SELECT * FROM sales WHERE 1=1"
    params = []

    if from_date:
        query += " AND created_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND created_at <= ?"
        params.append(to_date)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()

    # Contar total
    count_q = "SELECT COUNT(*) FROM sales WHERE 1=1"
    count_params = []
    if from_date:
        count_q += " AND created_at >= ?"
        count_params.append(from_date)
    if to_date:
        count_q += " AND created_at <= ?"
        count_params.append(to_date)
    if status:
        count_q += " AND status = ?"
        count_params.append(status)

    total = conn.execute(count_q, count_params).fetchone()[0]
    conn.close()

    return {"sales": rows_to_list(rows), "total": total, "limit": limit, "offset": offset}


@app.get("/api/sales/summary", tags=["Ventas"])
def get_sales_summary():
    """
    Resumen de ventas: hoy, esta semana, este mes.
    Compatible con el formato de csmology.com para el dashboard.
    """
    conn = get_db()
    now = datetime.now(TZ_OFFSET)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    def summary(from_ts: str) -> dict:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as count "
            "FROM sales WHERE created_at >= ? AND status = 'success'",
            (from_ts,),
        ).fetchone()
        return {"saleAmount": row["total"], "saleCount": row["count"]}

    result = {
        "today": summary(today_start),
        "week": summary(week_start),
        "month": summary(month_start),
        # Formato compatible con csmology: data[0]=hoy, data[1]=mes
        "data": [summary(today_start), summary(month_start)],
    }
    conn.close()
    return result


@app.get("/api/sales/by-product", tags=["Ventas"])
def get_sales_by_product(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Ventas agrupadas por producto (para gráficas)."""
    conn = get_db()
    query = """
        SELECT product_name, COUNT(*) as count, SUM(amount) as total
        FROM sales WHERE status = 'success'
    """
    params = []
    if from_date:
        query += " AND created_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND created_at <= ?"
        params.append(to_date)
    query += " GROUP BY product_name ORDER BY count DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"products": rows_to_list(rows)}


@app.get("/api/sales/by-day", tags=["Ventas"])
def get_sales_by_day(days: int = Query(30, le=365)):
    """Ventas por día (para gráfica de barras del dashboard)."""
    conn = get_db()
    since = (datetime.now(TZ_OFFSET) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT DATE(created_at) as date, COUNT(*) as count, SUM(amount) as total
        FROM sales WHERE status = 'success' AND created_at >= ?
        GROUP BY DATE(created_at) ORDER BY date
        """,
        (since,),
    ).fetchall()
    conn.close()
    return {"days": rows_to_list(rows)}


# ─────────────────────────────────────────────
# ENDPOINTS: Productos
# ─────────────────────────────────────────────

@app.get("/api/products", tags=["Productos"])
def get_products(active_only: bool = Query(False)):
    """Lista de productos (catálogo)."""
    conn = get_db()
    if active_only:
        rows = conn.execute("SELECT * FROM products WHERE active = 1 ORDER BY slot").fetchall()
    else:
        rows = conn.execute("SELECT * FROM products ORDER BY slot").fetchall()
    conn.close()
    return {"products": rows_to_list(rows), "total": len(rows)}


@app.post("/api/products", tags=["Productos"])
def create_product(product: ProductCreate):
    """Crear un producto nuevo."""
    conn = get_db()
    ts = now_local()
    cursor = conn.execute(
        "INSERT INTO products (name, price, slot, image, stock, active, category, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product.name, product.price, product.slot, product.image,
         product.stock, product.active, product.category, ts, ts),
    )
    conn.commit()
    pid = cursor.lastrowid
    conn.close()
    log_event("product_created", f"Producto #{pid}: {product.name}", "dashboard")
    return {"status": "ok", "product_id": pid}


@app.get("/api/products/{product_id}", tags=["Productos"])
def get_product(product_id: int):
    """Obtener un producto por ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Producto no encontrado")
    return row_to_dict(row)


@app.put("/api/products/{product_id}", tags=["Productos"])
async def update_product(product_id: int, update: ProductUpdate):
    """Actualizar producto (precio, foto, stock, etc.)."""
    conn = get_db()
    existing = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Producto no encontrado")

    fields = []
    values = []
    for field_name, val in update.model_dump(exclude_none=True).items():
        fields.append(f"{field_name} = ?")
        values.append(val)

    if fields:
        fields.append("updated_at = ?")
        values.append(now_local())
        values.append(product_id)
        conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    conn.close()
    log_event("product_updated", f"Producto #{product_id} actualizado", "dashboard")
    return {"status": "ok", "product_id": product_id}


@app.delete("/api/products/{product_id}", tags=["Productos"])
def delete_product(product_id: int):
    """Desactivar producto (soft delete)."""
    conn = get_db()
    conn.execute("UPDATE products SET active = 0, updated_at = ? WHERE id = ?",
                 (now_local(), product_id))
    conn.commit()
    conn.close()
    return {"status": "ok", "product_id": product_id, "action": "deactivated"}


# ─────────────────────────────────────────────
# ENDPOINTS: Máquina
# ─────────────────────────────────────────────

@app.get("/api/machine/status", tags=["Máquina"])
def get_machine_status():
    """Estado actual de la máquina."""
    conn = get_db()
    last = conn.execute(
        "SELECT * FROM machine_status ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()

    machine_code = "BC8A08520A50"
    return {
        "machine_code": machine_code,
        "online": manager.is_machine_online(machine_code),
        "last_report": row_to_dict(last) if last else None,
        "connections": manager.get_status(),
        "timestamp": now_local(),
    }


@app.post("/api/machine/status", tags=["Máquina"])
async def report_machine_status(report: MachineStatusReport):
    """La máquina reporta su estado."""
    conn = get_db()
    conn.execute(
        "INSERT INTO machine_status (online, ip_address, sw_version, uptime_sec, last_error, slot_status, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (report.online, report.ip_address, report.sw_version,
         report.uptime_sec, report.last_error, report.slot_status, now_local()),
    )
    conn.commit()
    conn.close()

    await manager.broadcast_to_dashboards({
        "type": "machine_status",
        "data": report.model_dump(),
        "timestamp": now_local(),
    })

    return {"status": "ok"}


@app.post("/api/machine/heartbeat", tags=["Máquina"])
async def machine_heartbeat():
    """Ping periódico de la máquina (cada 30s)."""
    machine_code = "BC8A08520A50"
    manager.last_heartbeat[machine_code] = now_local()
    return {"status": "ok", "timestamp": now_local()}


@app.post("/api/machine/command", tags=["Máquina"])
async def send_machine_command(cmd: MachineCommand):
    """
    Enviar comando a la máquina via WebSocket.
    Comandos: reboot, update_products, disable_sales, enable_sales, test_motor
    """
    machine_code = "BC8A08520A50"

    message = {
        "type": cmd.command,
        "params": cmd.params or {},
        "timestamp": now_local(),
    }

    sent = await manager.send_to_machine(machine_code, message)
    if not sent:
        log_event("command_failed", f"Comando '{cmd.command}' no enviado (máquina offline)", "dashboard")
        raise HTTPException(503, "Máquina no conectada")

    log_event("command_sent", f"Comando '{cmd.command}' enviado a {machine_code}", "dashboard")

    return {
        "status": "ok",
        "command": cmd.command,
        "machine_code": machine_code,
        "delivered": True,
        "timestamp": now_local(),
    }


# ─────────────────────────────────────────────
# ENDPOINTS: Inventario
# ─────────────────────────────────────────────

@app.get("/api/inventory", tags=["Inventario"])
def get_inventory():
    """Estado del inventario por slot."""
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.name, p.slot, p.stock, p.price, p.active,
               COALESCE(i.max_qty, 10) as max_qty,
               COALESCE(i.last_refill, '') as last_refill
        FROM products p
        LEFT JOIN inventory i ON p.id = i.product_id
        WHERE p.active = 1
        ORDER BY p.slot
    """).fetchall()
    conn.close()
    return {"inventory": rows_to_list(rows)}


@app.post("/api/inventory/refill", tags=["Inventario"])
def refill_inventory(update: InventoryUpdate):
    """Registrar reabastecimiento de un slot."""
    conn = get_db()
    ts = now_local()

    conn.execute("UPDATE products SET stock = ? WHERE id = ?", (update.quantity, update.product_id))

    conn.execute(
        "INSERT OR REPLACE INTO inventory (product_id, slot, quantity, max_qty, last_refill) "
        "VALUES (?, ?, ?, ?, ?)",
        (update.product_id, update.slot, update.quantity, update.max_qty, ts),
    )
    conn.commit()
    conn.close()

    log_event("refill", f"Producto #{update.product_id} slot {update.slot} → {update.quantity} unidades", "dashboard")
    return {"status": "ok", "timestamp": ts}


@app.get("/api/inventory/low-stock", tags=["Inventario"])
def get_low_stock(threshold: int = Query(3)):
    """Productos con stock bajo."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, slot, stock, price FROM products WHERE active = 1 AND stock <= ? ORDER BY stock",
        (threshold,),
    ).fetchall()
    conn.close()
    return {"low_stock": rows_to_list(rows), "threshold": threshold}


# ─────────────────────────────────────────────
# ENDPOINTS: Configuración
# ─────────────────────────────────────────────

@app.get("/api/config", tags=["Configuración"])
def get_config():
    """Configuración completa del sistema."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


@app.put("/api/config", tags=["Configuración"])
def update_config(cfg: ConfigUpdate):
    """Actualizar un valor de configuración."""
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (cfg.key, cfg.value))
    conn.commit()
    conn.close()
    log_event("config_updated", f"{cfg.key} = {cfg.value}", "dashboard")
    return {"status": "ok", "key": cfg.key, "value": cfg.value}


# ─────────────────────────────────────────────
# ENDPOINTS: Log de eventos
# ─────────────────────────────────────────────

@app.get("/api/events", tags=["Eventos"])
def get_events(
    event_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(100, le=500),
):
    """Consultar log de eventos."""
    conn = get_db()
    if event_type:
        rows = conn.execute(
            "SELECT * FROM event_log WHERE type = ? ORDER BY timestamp DESC LIMIT ?",
            (event_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM event_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return {"events": rows_to_list(rows)}


# ─────────────────────────────────────────────
# ENDPOINTS: Estadísticas (compatibilidad csmology)
# ─────────────────────────────────────────────

@app.post("/api/statistics/getSaleCount", tags=["Estadísticas"])
def get_sale_count_compat(body: dict):
    """
    Formato compatible con csmology.com para el dashboard v3.
    Recibe timePeriodList y devuelve data[0], data[1], etc.
    """
    conn = get_db()
    periods = body.get("timePeriodList", [])
    data = []

    for period in periods:
        start = period.get("startTime", "")
        end = period.get("endTime", "")
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as saleAmount, COUNT(*) as saleCount "
            "FROM sales WHERE created_at >= ? AND created_at <= ? AND status = 'success'",
            (start, end),
        ).fetchone()
        data.append({"saleAmount": row["saleAmount"], "saleCount": row["saleCount"]})

    conn.close()
    return {"errInfo": "操作成功", "errCode": "0000", "data": data}


# ─────────────────────────────────────────────
# WebSocket: Máquina
# ─────────────────────────────────────────────

@app.websocket("/ws/vmc")
async def websocket_machine(ws: WebSocket):
    """
    WebSocket para la máquina expendedora.
    La máquina se conecta aquí para recibir comandos en tiempo real.
    """
    machine_code = "BC8A08520A50"
    await manager.connect_machine(ws, machine_code)
    log_event("ws_connect", f"Máquina {machine_code} conectada por WebSocket", "machine")

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "heartbeat":
                manager.last_heartbeat[machine_code] = now_local()
                await ws.send_json({"type": "heartbeat_ack", "timestamp": now_local()})

            elif msg_type == "sale_complete":
                # La máquina reporta venta completada
                await manager.broadcast_to_dashboards(data)
                log_event("sale_ws", json.dumps(data, ensure_ascii=False), "machine")

            elif msg_type == "error":
                error_msg = data.get("message", "Error desconocido")
                logger.error(f"Error de máquina: {error_msg}")
                log_event("machine_error", error_msg, "machine", json.dumps(data))
                await manager.broadcast_to_dashboards(data)

            elif msg_type == "slot_status":
                # Status de slots del dispensador (heartbeat SH)
                await manager.broadcast_to_dashboards(data)

            elif msg_type == "bill_inserted":
                # Billete insertado
                await manager.broadcast_to_dashboards(data)
                log_event("bill_inserted", f"Billete: ${data.get('amount', 0)}", "machine")

            else:
                logger.info(f"Mensaje WS de máquina: {data}")
                await manager.broadcast_to_dashboards(data)

    except WebSocketDisconnect:
        manager.disconnect_machine(machine_code)
        log_event("ws_disconnect", f"Máquina {machine_code} desconectada", "machine")
        await manager.broadcast_to_dashboards({
            "type": "machine_disconnected",
            "machine_code": machine_code,
            "timestamp": now_local(),
        })


# ─────────────────────────────────────────────
# WebSocket: Dashboard
# ─────────────────────────────────────────────

@app.websocket("/ws/dashboard")
async def websocket_dashboard(ws: WebSocket):
    """
    WebSocket para el dashboard de escritorio.
    Recibe actualizaciones en tiempo real de ventas y estado.
    """
    await manager.connect_dashboard(ws)
    log_event("ws_connect", "Dashboard conectado", "dashboard")

    # Enviar estado inicial
    await ws.send_json({
        "type": "init",
        "connections": manager.get_status(),
        "timestamp": now_local(),
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "command":
                # Dashboard envía comando a la máquina
                cmd = data.get("command", "")
                params = data.get("params", {})
                machine_code = data.get("machine_code", "BC8A08520A50")
                sent = await manager.send_to_machine(machine_code, {
                    "type": cmd,
                    "params": params,
                    "timestamp": now_local(),
                })
                await ws.send_json({
                    "type": "command_ack",
                    "command": cmd,
                    "delivered": sent,
                    "timestamp": now_local(),
                })

            elif msg_type == "ping":
                await ws.send_json({"type": "pong", "timestamp": now_local()})

    except WebSocketDisconnect:
        manager.disconnect_dashboard(ws)
        log_event("ws_disconnect", "Dashboard desconectado", "dashboard")


# ─────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    print()
    print("=" * 60)
    print("  VMC Control Center — Servidor Local v2.0")
    print("=" * 60)
    print(f"  Servidor:   http://0.0.0.0:{PORT}")
    print(f"  API Docs:   http://localhost:{PORT}/docs")
    print(f"  Base datos: {DB_PATH}")
    print(f"  Máquina:    BC8A08520A50")
    print("=" * 60)
    print()

    uvicorn.run(
        "vmc_server:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
