#!/usr/bin/env python3
"""Orbit Shop — a small multi-service app that emits traces, metrics, and logs."""

from __future__ import annotations

import logging
import os
import random
import signal
import sys
import threading
import time
from typing import Any

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

ROLE = os.environ.get("SHOP_ROLE", "frontend")
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", f"shop-{ROLE}")
OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318").rstrip("/")
API_URL = os.environ.get("API_URL", "http://shop-api:8080").rstrip("/")
WORKER_URL = os.environ.get("WORKER_URL", "http://shop-worker:8080").rstrip("/")
TARGET_URL = os.environ.get("TARGET_URL", "http://shop-frontend:8080").rstrip("/")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
ERROR_RATE = float(os.environ.get("ERROR_RATE", "0.08"))
SLOW_RATE = float(os.environ.get("SLOW_RATE", "0.12"))
LOADGEN_INTERVAL = float(os.environ.get("LOADGEN_INTERVAL", "0.7"))

PRODUCTS = [
    {"id": "nebula-poster", "name": "Helix Nebula poster", "price_cents": 2400, "stock": 80},
    {"id": "meteorite", "name": "Campo del Cielo meteorite", "price_cents": 8900, "stock": 18},
    {"id": "star-atlas", "name": "Uranometria star atlas", "price_cents": 5600, "stock": 24},
    {"id": "telescope", "name": "80mm refractor telescope", "price_cents": 21900, "stock": 6},
    {"id": "moon-lamp", "name": "3D moon lamp", "price_cents": 3900, "stock": 40},
    {"id": "planisphere", "name": "Northern sky planisphere", "price_cents": 1800, "stock": 55},
]

USERS = ["ada", "grace", "alan", "katie", "linus", "margaret"]

stock: dict[str, int] = {p["id"]: p["stock"] for p in PRODUCTS}
stock_lock = threading.Lock()
stop_event = threading.Event()

log = logging.getLogger("shop")


def setup_telemetry() -> None:
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.namespace": "orbit-shop",
            "service.version": "1.0.0",
            "deployment.environment": "lab",
            "shop.role": ROLE,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{OTLP_ENDPOINT}/v1/metrics"),
        export_interval_millis=10000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTLP_ENDPOINT}/v1/logs"))
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    )
    logging.getLogger().addHandler(handler)

    LoggingInstrumentor().instrument(set_logging_format=False)
    RequestsInstrumentor().instrument()
    try:
        SystemMetricsInstrumentor().instrument()
    except Exception:
        log.warning("system metrics instrumentation skipped", exc_info=True)


setup_telemetry()
tracer = trace.get_tracer("orbit-shop")
meter = metrics.get_meter("orbit-shop")

orders_counter = meter.create_counter(
    "shop.orders",
    unit="1",
    description="Checkout attempts",
)
order_value = meter.create_histogram(
    "shop.order.value",
    unit="USD",
    description="Checkout order value in dollars",
)
catalog_views = meter.create_counter(
    "shop.catalog.views",
    unit="1",
    description="Product detail views",
)
payments_counter = meter.create_counter(
    "shop.payments",
    unit="1",
    description="Payment attempts",
)
shipments_counter = meter.create_counter(
    "shop.shipments",
    unit="1",
    description="Shipment label attempts",
)
if ROLE == "api":
    meter.create_observable_gauge(
        "shop.inventory",
        callbacks=[
            lambda options: [
                metrics.Observation(qty, {"product.id": pid}) for pid, qty in stock.items()
            ]
        ],
        unit="1",
        description="Units remaining in inventory",
    )

app = FastAPI(title="Orbit Shop", docs_url=None, redoc_url=None)


def maybe_slow(kind: str = "db") -> None:
    if random.random() < SLOW_RATE:
        delay = random.uniform(0.6, 2.2)
        with tracer.start_as_current_span(f"slow.{kind}") as span:
            span.set_attribute("shop.slow", True)
            span.set_attribute("shop.delay_seconds", delay)
            log.warning("injected slow %s path (%.2fs)", kind, delay)
            time.sleep(delay)


def maybe_error(message: str, rate: float | None = None) -> None:
    if random.random() < (ERROR_RATE if rate is None else rate):
        log.error("injected failure: %s", message)
        raise HTTPException(status_code=503, detail=message)


def product_or_404(product_id: str) -> dict[str, Any]:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise HTTPException(status_code=404, detail=f"unknown product {product_id}")


def json_error(request: Request, exc: HTTPException) -> JSONResponse:
    span = trace.get_current_span()
    span.set_status(Status(StatusCode.ERROR, str(exc.detail)))
    span.record_exception(exc)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.add_exception_handler(HTTPException, json_error)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "role": ROLE, "service": SERVICE_NAME}


# ---------------------------------------------------------------------------
# API (catalog + inventory)
# ---------------------------------------------------------------------------


@app.get("/products")
def list_products() -> list[dict[str, Any]]:
    maybe_slow("catalog")
    log.info("listed %d products", len(PRODUCTS))
    with stock_lock:
        return [{**p, "stock": stock[p["id"]]} for p in PRODUCTS]


@app.get("/products/{product_id}")
def get_product(product_id: str) -> dict[str, Any]:
    maybe_slow("catalog")
    product = product_or_404(product_id)
    with tracer.start_as_current_span("db.product_lookup") as span:
        span.set_attribute("db.system", "memory")
        span.set_attribute("product.id", product_id)
        time.sleep(random.uniform(0.01, 0.05))
    catalog_views.add(1, {"product.id": product_id})
    log.info("fetched product %s", product_id)
    with stock_lock:
        return {**product, "stock": stock[product_id]}


@app.get("/recommendations")
def recommendations() -> list[dict[str, Any]]:
    maybe_slow("recommend")
    picks = random.sample(PRODUCTS, k=3)
    log.info("recommended %s", ",".join(p["id"] for p in picks))
    return [{"id": p["id"], "name": p["name"]} for p in picks]


@app.post("/inventory/reserve")
def reserve(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id")
    qty = int(body.get("qty", 1))
    product = product_or_404(product_id)
    maybe_error("inventory backend timeout")
    with tracer.start_as_current_span("inventory.reserve") as span:
        span.set_attribute("product.id", product_id)
        span.set_attribute("product.qty", qty)
        with stock_lock:
            available = stock[product_id]
            span.set_attribute("inventory.available", available)
            if available < qty:
                log.warning("out of stock for %s (want %d have %d)", product_id, qty, available)
                raise HTTPException(status_code=409, detail=f"{product_id} is out of stock")
            stock[product_id] = available - qty
            remaining = stock[product_id]
        log.info("reserved %dx %s, remaining=%d", qty, product_id, remaining)
        return {"product_id": product_id, "qty": qty, "remaining": remaining, "price_cents": product["price_cents"]}


@app.post("/inventory/release")
def release(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id")
    qty = int(body.get("qty", 1))
    product_or_404(product_id)
    with stock_lock:
        stock[product_id] += qty
        remaining = stock[product_id]
    log.info("released %dx %s, remaining=%d", qty, product_id, remaining)
    return {"product_id": product_id, "remaining": remaining}


# ---------------------------------------------------------------------------
# Worker (payments + shipping)
# ---------------------------------------------------------------------------


@app.post("/pay")
def pay(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id", "")
    amount_cents = int(body.get("amount_cents", 0))
    user = body.get("user", "anonymous")
    with tracer.start_as_current_span("payment.authorize") as span:
        span.set_attribute("payment.provider", "orbitpay")
        span.set_attribute("user.id", user)
        span.set_attribute("payment.amount_cents", amount_cents)
        time.sleep(random.uniform(0.08, 0.25))
        fail_rate = 0.35 if product_id == "telescope" else ERROR_RATE
        if random.random() < fail_rate:
            payments_counter.add(1, {"status": "declined", "product.id": product_id})
            log.error("payment declined for %s user=%s amount=%d", product_id, user, amount_cents)
            span.set_status(Status(StatusCode.ERROR, "declined"))
            raise HTTPException(status_code=402, detail="card declined")
        auth = f"pay_{random.randint(100000, 999999)}"
        payments_counter.add(1, {"status": "authorized", "product.id": product_id})
        log.info("payment authorized %s user=%s amount=%d", auth, user, amount_cents)
        return {"auth": auth, "amount_cents": amount_cents}


@app.post("/ship")
def ship(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id", "")
    with tracer.start_as_current_span("shipping.label") as span:
        span.set_attribute("shipping.carrier", "orbitransit")
        span.set_attribute("product.id", product_id)
        time.sleep(random.uniform(0.05, 0.18))
        try:
            maybe_error("shipping label printer offline", rate=0.04)
        except HTTPException:
            shipments_counter.add(1, {"status": "failed", "product.id": product_id})
            raise
        tracking = f"ORB{random.randint(10_000_000, 99_999_999)}"
        shipments_counter.add(1, {"status": "ok", "product.id": product_id})
        log.info("shipment created tracking=%s product=%s", tracking, product_id)
        return {"tracking": tracking, "carrier": "orbitransit"}


@app.post("/notify")
def notify(body: dict[str, Any]) -> dict[str, str]:
    user = body.get("user", "anonymous")
    tracking = body.get("tracking", "")
    log.info("notified %s tracking=%s", user, tracking)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Frontend (UI + BFF)
# ---------------------------------------------------------------------------


def downstream(method: str, url: str, **kwargs: Any) -> Any:
    response = requests.request(method, url, timeout=5, **kwargs)
    if response.status_code >= 400:
        try:
            detail = response.json().get("error") or response.text
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    if response.content:
        return response.json()
    return {}


@app.get("/api/products")
def frontend_products() -> Any:
    return downstream("GET", f"{API_URL}/products")


@app.get("/api/products/{product_id}")
def frontend_product(product_id: str) -> Any:
    product = downstream("GET", f"{API_URL}/products/{product_id}")
    recs = downstream("GET", f"{API_URL}/recommendations")
    product["recommendations"] = recs
    return product


@app.post("/api/checkout")
def frontend_checkout(body: dict[str, Any]) -> Any:
    product_id = body.get("product_id") or random.choice(PRODUCTS)["id"]
    qty = int(body.get("qty", 1))
    user = body.get("user") or random.choice(USERS)
    span = trace.get_current_span()
    span.set_attribute("user.id", user)
    span.set_attribute("product.id", product_id)
    span.set_attribute("product.qty", qty)

    reserved = False
    try:
        reservation = downstream(
            "POST", f"{API_URL}/inventory/reserve", json={"product_id": product_id, "qty": qty}
        )
        reserved = True
        amount = reservation["price_cents"] * qty
        payment = downstream(
            "POST",
            f"{WORKER_URL}/pay",
            json={"product_id": product_id, "amount_cents": amount, "user": user},
        )
        shipment = downstream(
            "POST", f"{WORKER_URL}/ship", json={"product_id": product_id, "user": user}
        )
        downstream(
            "POST",
            f"{WORKER_URL}/notify",
            json={"user": user, "tracking": shipment["tracking"], "product_id": product_id},
        )
        dollars = amount / 100.0
        orders_counter.add(1, {"status": "ok", "product.id": product_id, "user.id": user})
        order_value.record(dollars, {"product.id": product_id, "user.id": user})
        log.info(
            "checkout ok user=%s product=%s qty=%d total=%.2f tracking=%s",
            user,
            product_id,
            qty,
            dollars,
            shipment["tracking"],
        )
        return {
            "status": "ok",
            "user": user,
            "product_id": product_id,
            "qty": qty,
            "total_cents": amount,
            "auth": payment["auth"],
            "tracking": shipment["tracking"],
        }
    except HTTPException as exc:
        reason = {
            402: "card_declined",
            409: "out_of_stock",
            503: "backend_timeout",
        }.get(exc.status_code, "error")
        orders_counter.add(
            1, {"status": "failed", "product.id": product_id, "user.id": user, "reason": reason}
        )
        log.error("checkout failed user=%s product=%s reason=%s: %s", user, product_id, reason, exc.detail)
        if reserved:
            try:
                downstream(
                    "POST", f"{API_URL}/inventory/release", json={"product_id": product_id, "qty": qty}
                )
            except Exception:
                log.exception("failed to release inventory after checkout error")
        raise


@app.get("/api/boom")
def boom() -> None:
    log.error("intentional explosion from %s", SERVICE_NAME)
    raise HTTPException(status_code=500, detail="the telescope mount collapsed")


@app.get("/api/slow")
def slow() -> dict[str, Any]:
    delay = random.uniform(1.5, 3.0)
    with tracer.start_as_current_span("intentionally.slow") as span:
        span.set_attribute("shop.delay_seconds", delay)
        time.sleep(delay)
    log.warning("slow endpoint finished in %.2fs", delay)
    return {"status": "ok", "delay": delay}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    cards = "".join(
        f"""<button class="card" onclick="checkout('{p['id']}')">
              <strong>{p['name']}</strong>
              <span class="price">${p['price_cents']/100:.2f}</span>
              <em>buy {p['id']}</em>
            </button>"""
        for p in PRODUCTS
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Orbit Shop</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #141a2e;
      --ink: #e8eefc;
      --muted: #8b97b8;
      --accent: #ffb020;
      --ok: #3ddc97;
      --bad: #ff5d73;
      --line: #243056;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(1200px 500px at 10% -10%, #1b2a55 0%, transparent 55%),
        radial-gradient(900px 400px at 110% 10%, #3a1d10 0%, transparent 50%),
        var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 28px 32px 8px; display: flex; justify-content: space-between; gap: 16px;
      align-items: baseline; flex-wrap: wrap;
    }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0.04em; }}
    h1 span {{ color: var(--accent); }}
    .sub {{ color: var(--muted); max-width: 52ch; }}
    main {{ padding: 16px 32px 48px; display: grid; gap: 18px; }}
    .row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    button, a.btn {{
      background: var(--panel); color: var(--ink); border: 1px solid var(--line);
      border-radius: 10px; padding: 10px 14px; cursor: pointer; font: inherit;
      text-decoration: none; display: inline-flex; align-items: center; gap: 8px;
    }}
    button:hover, a.btn:hover {{ border-color: var(--accent); }}
    button.danger {{ border-color: #5a2430; }}
    .grid {{
      display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px;
    }}
    .card {{
      text-align: left; min-height: 110px; flex-direction: column; align-items: flex-start;
      justify-content: space-between; width: 100%;
    }}
    .card .price {{ color: var(--accent); font-variant-numeric: tabular-nums; }}
    .card em {{ color: var(--muted); font-size: 12px; }}
    #log {{
      background: #070b16; border: 1px solid var(--line); border-radius: 12px;
      padding: 12px 14px; min-height: 220px; font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 13px; line-height: 1.45; white-space: pre-wrap;
    }}
    .ok {{ color: var(--ok); }}
    .bad {{ color: var(--bad); }}
    .hint {{ color: var(--muted); font-size: 13px; }}
    code {{ color: var(--accent); }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Orbit <span>Shop</span></h1>
      <p class="sub">A noisy little store that feeds Grafana with metrics, logs, and traces.
      Background traffic is already running; use the buttons to force interesting shapes.</p>
    </div>
    <a class="btn" id="grafana-link" href="http://127.0.0.1:3000" target="_blank" rel="noreferrer">Open Grafana</a>
  </header>
  <main>
    <div class="row">
      <button onclick="browse()">Browse catalog</button>
      <button onclick="checkout()">Random checkout</button>
      <button onclick="hit('/api/slow')">Slow request</button>
      <button class="danger" onclick="hit('/api/boom')">Force 500</button>
      <button onclick="burst()">Burst x20</button>
    </div>
    <div class="grid">{cards}</div>
    <div class="hint">Grafana: admin / changeme · Explore Loki <code>{{service_namespace="orbit-shop"}}</code> · Tempo <code>{{resource.service.namespace="orbit-shop"}}</code></div>
    <div id="log">ready. click around, then jump to Grafana.</div>
  </main>
  <script>
    const grafanaLink = document.getElementById('grafana-link');
    grafanaLink.href = location.protocol + '//' + location.hostname + ':3000';
    const logEl = document.getElementById('log');
    function line(ok, text) {{
      const cls = ok ? 'ok' : 'bad';
      const ts = new Date().toISOString().slice(11, 23);
      logEl.innerHTML = `<span class="${{cls}}">${{ts}}  ${{text}}</span>\\n` + logEl.innerHTML;
    }}
    async function hit(url, opts) {{
      const t0 = performance.now();
      try {{
        const res = await fetch(url, opts);
        const body = await res.json();
        const ms = (performance.now() - t0).toFixed(0);
        line(res.ok, `${{opts?.method || 'GET'}} ${{url}} → ${{res.status}} ${{ms}}ms  ${{JSON.stringify(body)}}`);
      }} catch (err) {{
        line(false, `${{url}} failed: ${{err}}`);
      }}
    }}
    function browse() {{ return hit('/api/products'); }}
    function checkout(id) {{
      const payload = id ? {{product_id: id}} : {{}};
      return hit('/api/checkout', {{
        method: 'POST',
        headers: {{'content-type': 'application/json'}},
        body: JSON.stringify(payload),
      }});
    }}
    async function burst() {{
      await Promise.all(Array.from({{length: 20}}, (_, i) => {{
        const pick = i % 5;
        if (pick === 0) return hit('/api/boom');
        if (pick === 1) return hit('/api/slow');
        if (pick === 2) return browse();
        return checkout();
      }}));
    }}
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Load generator
# ---------------------------------------------------------------------------


def loadgen() -> None:
    session = requests.Session()
    actions = [
        ("browse", 0.40),
        ("product", 0.22),
        ("checkout", 0.26),
        ("error", 0.07),
        ("slow", 0.05),
    ]
    names, weights = zip(*actions)
    log.info("loadgen targeting %s interval=%.2fs", TARGET_URL, LOADGEN_INTERVAL)
    while not stop_event.wait(LOADGEN_INTERVAL + random.uniform(-0.2, 0.4)):
        action = random.choices(names, weights=weights, k=1)[0]
        user = random.choice(USERS)
        try:
            if action == "browse":
                session.get(f"{TARGET_URL}/api/products", timeout=8, headers={"X-User": user})
            elif action == "product":
                pid = random.choice(PRODUCTS)["id"]
                session.get(f"{TARGET_URL}/api/products/{pid}", timeout=8, headers={"X-User": user})
            elif action == "checkout":
                session.post(
                    f"{TARGET_URL}/api/checkout",
                    json={"product_id": random.choice(PRODUCTS)["id"], "user": user, "qty": 1},
                    timeout=8,
                )
            elif action == "error":
                session.get(f"{TARGET_URL}/api/boom", timeout=8)
            elif action == "slow":
                session.get(f"{TARGET_URL}/api/slow", timeout=12)
        except Exception as exc:
            log.warning("loadgen %s failed: %s", action, exc)


def serve() -> None:
    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT, log_level="info", access_log=True)


def main() -> None:
    def handle_stop(signum, _frame):
        log.info("received signal %s, shutting down", signum)
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    FastAPIInstrumentor.instrument_app(app)
    log.info("starting role=%s service=%s otlp=%s", ROLE, SERVICE_NAME, OTLP_ENDPOINT)
    if ROLE == "loadgen":
        loadgen()
        return
    if ROLE == "api":
        def restock_loop() -> None:
            while not stop_event.wait(90):
                with stock_lock:
                    for product in PRODUCTS:
                        target = product["stock"]
                        if stock[product["id"]] < target:
                            stock[product["id"]] = min(target, stock[product["id"]] + max(1, target // 8))
                log.info("inventory restock pass complete")

        threading.Thread(target=restock_loop, name="restock", daemon=True).start()
    serve()


if __name__ == "__main__":
    main()
