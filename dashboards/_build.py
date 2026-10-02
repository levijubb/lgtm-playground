#!/usr/bin/env python3
"""Build Orbit Shop Grafana dashboards. Run from this directory: python3 _build.py"""

from __future__ import annotations

import json
from pathlib import Path

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
SHOP = 'service_namespace="orbit-shop"'
FRONT = 'service_name="shop-frontend"'
API = 'service_name="shop-api"'
WORKER = 'service_name="shop-worker"'

def _links(pairs, shop=False):
    items = [
        {
            "asDropdown": False,
            "icon": "dashboard",
            "includeVars": False,
            "keepTime": True,
            "tags": [],
            "targetBlank": False,
            "title": title,
            "type": "link",
            "url": url,
        }
        for title, url in pairs
    ]
    if shop:
        items.append(
            {
                "asDropdown": False,
                "icon": "external link",
                "includeVars": False,
                "keepTime": False,
                "tags": [],
                "targetBlank": True,
                "title": "Shop UI",
                "type": "link",
                "url": "http://127.0.0.1:8081/",
            }
        )
    return items


BUSINESS_LINKS = _links(
    [
        ("Sales", "/d/orbit-shop-sales"),
        ("Catalog", "/d/orbit-shop-catalog"),
        ("Checkout", "/d/orbit-shop-checkout"),
        ("Fulfillment", "/d/orbit-shop-fulfillment"),
        ("Golden signals", "/d/orbit-shop-red"),
    ],
    shop=True,
)
TECH_LINKS = _links(
    [
        ("Golden signals", "/d/orbit-shop-red"),
        ("HTTP", "/d/orbit-shop-http"),
        ("Traces", "/d/orbit-shop-traces"),
        ("Logs", "/d/orbit-shop-logs"),
        ("Runtime", "/d/orbit-shop-runtime"),
        ("Stack", "/d/orbit-shop-stack"),
        ("Sales", "/d/orbit-shop-sales"),
    ],
    shop=True,
)

SVC = 'service_namespace="orbit-shop",service_name=~"$service"'
SPAN_SVC = 'service=~"$service"'


def timeseries_custom():
    return {
        "drawStyle": "line",
        "fillOpacity": 18,
        "lineWidth": 2,
        "pointSize": 5,
        "showPoints": "never",
        "spanNulls": True,
        "stacking": {"mode": "none", "group": "A"},
        "gradientMode": "opacity",
        "axisBorderShow": False,
        "barAlignment": 0,
        "barWidthFactor": 0.6,
        "insertNulls": False,
        "scaleDistribution": {"type": "linear"},
        "thresholdsStyle": {"mode": "off"},
    }


def target(expr: str, legend: str, ref: str = "A", instant: bool = False, fmt: str | None = None):
    t = {
        "datasource": PROM,
        "editorMode": "code",
        "expr": expr,
        "legendFormat": legend,
        "range": not instant,
        "refId": ref,
    }
    if instant:
        t["instant"] = True
        t["range"] = False
    if fmt:
        t["format"] = fmt
    return t


def panel_base(pid, title, x, y, w, h, ptype):
    return {
        "id": pid,
        "title": title,
        "type": ptype,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": PROM,
    }


def timeseries(pid, title, x, y, w, h, expr, legend, unit="", stacked=False, desc=""):
    custom = timeseries_custom()
    if stacked:
        custom["stacking"] = {"mode": "normal", "group": "A"}
        custom["fillOpacity"] = 40
    p = panel_base(pid, title, x, y, w, h, "timeseries")
    p["description"] = desc
    p["fieldConfig"] = {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": custom,
            "min": 0,
            "unit": unit,
        },
        "overrides": [],
    }
    p["options"] = {
        "legend": {"calcs": ["mean", "lastNotNull"], "displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    p["targets"] = [target(expr, legend)]
    return p


def multi_ts(pid, title, x, y, w, h, targets, unit="", stacked=False, desc=""):
    p = timeseries(pid, title, x, y, w, h, targets[0][0], targets[0][1], unit, stacked, desc)
    p["targets"] = [target(expr, legend, ref=chr(65 + i)) for i, (expr, legend) in enumerate(targets)]
    return p


def stat(pid, title, x, y, w, h, expr, unit="", color="blue", desc="", spark=True):
    p = panel_base(pid, title, x, y, w, h, "stat")
    p["description"] = desc
    p["fieldConfig"] = {
        "defaults": {
            "color": {"mode": "fixed", "fixedColor": color},
            "decimals": 1,
            "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]},
            "unit": unit,
            "noValue": "—",
        },
        "overrides": [],
    }
    p["options"] = {
        "colorMode": "background",
        "graphMode": "area" if spark else "none",
        "justifyMode": "auto",
        "orientation": "auto",
        "percentChangeColorMode": "standard",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "showPercentChange": False,
        "textMode": "auto",
        "wideLayout": True,
    }
    p["targets"] = [target(expr, title, instant=True)]
    return p


def gauge(pid, title, x, y, w, h, expr, legend, unit="", maxv=100, desc=""):
    p = panel_base(pid, title, x, y, w, h, "gauge")
    p["description"] = desc
    p["fieldConfig"] = {
        "defaults": {
            "color": {"mode": "thresholds"},
            "max": maxv,
            "min": 0,
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "red", "value": None},
                    {"color": "orange", "value": maxv * 0.12},
                    {"color": "green", "value": maxv * 0.35},
                ],
            },
            "unit": unit,
        },
        "overrides": [],
    }
    p["options"] = {
        "minVizHeight": 75,
        "minVizWidth": 75,
        "orientation": "auto",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "showThresholdLabels": False,
        "showThresholdMarkers": True,
        "sizing": "auto",
    }
    p["targets"] = [target(expr, legend)]
    return p


def bargauge(pid, title, x, y, w, h, expr, legend, unit="", desc="", maxv=None):
    p = panel_base(pid, title, x, y, w, h, "bargauge")
    p["description"] = desc
    defaults = {
        "color": {"mode": "palette-classic"},
        "min": 0,
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
        "unit": unit,
    }
    if maxv is not None:
        defaults["max"] = maxv
        defaults["color"] = {"mode": "thresholds"}
        defaults["thresholds"] = {
            "mode": "absolute",
            "steps": [
                {"color": "red", "value": None},
                {"color": "orange", "value": maxv * 0.12},
                {"color": "green", "value": maxv * 0.35},
            ],
        }
    p["fieldConfig"] = {"defaults": defaults, "overrides": []}
    p["options"] = {
        "displayMode": "gradient",
        "maxVizHeight": 300,
        "minVizHeight": 16,
        "namePlacement": "auto",
        "orientation": "horizontal",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "showUnfilled": True,
        "sizing": "auto",
        "valueMode": "color",
    }
    p["targets"] = [target(expr, legend, instant=True)]
    return p


def pie(pid, title, x, y, w, h, expr, legend, unit="", desc=""):
    p = panel_base(pid, title, x, y, w, h, "piechart")
    p["description"] = desc
    p["fieldConfig"] = {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "unit": unit,
        },
        "overrides": [],
    }
    p["options"] = {
        "legend": {
            "displayMode": "table",
            "placement": "right",
            "showLegend": True,
            "values": ["value", "percent"],
        },
        "pieType": "donut",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "tooltip": {"mode": "single", "sort": "desc"},
    }
    p["targets"] = [target(expr, legend, instant=True)]
    return p


def logs(pid, title, x, y, w, h, expr, desc=""):
    p = panel_base(pid, title, x, y, w, h, "logs")
    p["datasource"] = LOKI
    p["description"] = desc
    p["options"] = {
        "dedupStrategy": "none",
        "enableLogDetails": True,
        "prettifyLogMessage": False,
        "showCommonLabels": False,
        "showLabels": False,
        "showTime": True,
        "sortOrder": "Descending",
        "wrapLogMessage": True,
    }
    p["targets"] = [
        {
            "datasource": LOKI,
            "editorMode": "code",
            "expr": expr,
            "queryType": "range",
            "refId": "A",
        }
    ]
    return p


def text(pid, title, x, y, w, h, markdown):
    p = panel_base(pid, title, x, y, w, h, "text")
    p["transparent"] = True
    p["options"] = {"code": {"language": "markdown", "showLineNumbers": False, "showMiniMap": False}, "content": markdown, "mode": "markdown"}
    return p


def service_var():
    return {
        "allValue": ".*",
        "current": {"selected": True, "text": "All", "value": "$__all"},
        "datasource": PROM,
        "definition": 'label_values(http_server_duration_milliseconds_count{service_namespace="orbit-shop"}, service_name)',
        "includeAll": True,
        "label": "Service",
        "multi": True,
        "name": "service",
        "query": 'label_values(http_server_duration_milliseconds_count{service_namespace="orbit-shop"}, service_name)',
        "refresh": 2,
        "regex": "",
        "sort": 1,
        "type": "query",
    }


def heatmap(pid, title, x, y, w, h, expr, unit="ms", desc=""):
    p = panel_base(pid, title, x, y, w, h, "heatmap")
    p["description"] = desc
    p["fieldConfig"] = {
        "defaults": {
            "custom": {
                "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                "scaleDistribution": {"type": "linear"},
            }
        },
        "overrides": [],
    }
    p["options"] = {
        "calculate": False,
        "cellGap": 1,
        "color": {
            "exponent": 0.5,
            "fill": "dark-orange",
            "mode": "scheme",
            "reverse": False,
            "scale": "exponential",
            "scheme": "Spectral",
            "steps": 64,
        },
        "exemplars": {"color": "rgba(255,0,255,0.7)"},
        "filterValues": {"le": 1e-9},
        "legend": {"show": True},
        "rowsFrame": {"layout": "auto"},
        "tooltip": {"mode": "single", "showColorScale": False, "yHistogram": False},
        "yAxis": {"axisPlacement": "left", "reverse": False, "unit": unit},
    }
    t = target(expr, "{{le}}")
    t["format"] = "heatmap"
    p["targets"] = [t]
    return p


def loki_ts(pid, title, x, y, w, h, expr, legend, unit="loki"):
    p = timeseries(pid, title, x, y, w, h, expr, legend, unit=unit)
    p["datasource"] = LOKI
    p["targets"] = [
        {
            "datasource": LOKI,
            "editorMode": "code",
            "expr": expr,
            "legendFormat": legend,
            "queryType": "range",
            "refId": "A",
        }
    ]
    return p


def dash(uid, title, desc, panels, tags, links=None, templating=None):
    return {
        "annotations": {"list": []},
        "description": desc,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": links if links is not None else BUSINESS_LINKS,
        "liveNow": True,
        "panels": panels,
        "refresh": "10s",
        "schemaVersion": 39,
        "tags": tags,
        "templating": {"list": templating or []},
        "time": {"from": "now-1h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
    }


def sales():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Sales\nRevenue and orders in the **selected time range**. Telescope declines a lot on purpose — check **Checkout** if conversion falls over.",
        ),
        stat(
            2,
            "Revenue",
            0,
            3,
            4,
            5,
            f'sum(increase(shop_order_value_USD_sum{{{FRONT}}}[$__range]))',
            unit="currencyUSD",
            color="green",
            desc="Successful checkout value in the time range",
        ),
        stat(
            3,
            "Orders paid",
            4,
            3,
            4,
            5,
            f'sum(increase(shop_orders_total{{{FRONT},status="ok"}}[$__range]))',
            unit="short",
            color="blue",
        ),
        stat(
            4,
            "Avg order value",
            8,
            3,
            4,
            5,
            f'sum(increase(shop_order_value_USD_sum{{{FRONT}}}[$__range])) / clamp_min(sum(increase(shop_order_value_USD_count{{{FRONT}}}[$__range])), 1)',
            unit="currencyUSD",
            color="purple",
        ),
        stat(
            5,
            "Checkout conversion",
            12,
            3,
            4,
            5,
            f'sum(increase(shop_orders_total{{{FRONT},status="ok"}}[$__range])) / clamp_min(sum(increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/checkout"}}[$__range])), 1)',
            unit="percentunit",
            color="orange",
            desc="Paid orders / checkout attempts",
        ),
        stat(
            6,
            "Failed checkouts",
            16,
            3,
            4,
            5,
            f'sum(increase(shop_orders_total{{{FRONT},status="failed"}}[$__range]))',
            unit="short",
            color="red",
        ),
        stat(
            7,
            "Browse → paid",
            20,
            3,
            4,
            5,
            f'sum(increase(shop_orders_total{{{FRONT},status="ok"}}[$__range])) / clamp_min(sum(increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/products"}}[$__range])), 1)',
            unit="percentunit",
            color="yellow",
            desc="Paid orders / catalog list views",
        ),
        timeseries(
            8,
            "Revenue per hour",
            0,
            8,
            16,
            9,
            f'sum by (product_id) (rate(shop_order_value_USD_sum{{{FRONT}}}[5m]) * 3600)',
            "{{product_id}}",
            unit="currencyUSD",
            stacked=True,
            desc="Stacked by SKU",
        ),
        pie(
            9,
            "Revenue mix",
            16,
            8,
            8,
            9,
            f'sum by (product_id) (increase(shop_order_value_USD_sum{{{FRONT}}}[$__range]))',
            "{{product_id}}",
            unit="currencyUSD",
        ),
        timeseries(
            10,
            "Orders paid vs failed",
            0,
            17,
            12,
            8,
            f'sum by (status) (rate(shop_orders_total{{{FRONT}}}[5m]))',
            "{{status}}",
            unit="ops",
        ),
        bargauge(
            11,
            "Top customers (revenue)",
            12,
            17,
            12,
            8,
            f'sum by (user_id) (increase(shop_order_value_USD_sum{{{FRONT}}}[$__range]))',
            "{{user_id}}",
            unit="currencyUSD",
            desc="Fake shoppers the loadgen uses",
        ),
        bargauge(
            12,
            "Units sold by SKU",
            0,
            25,
            24,
            8,
            f'sum by (product_id) (increase(shop_orders_total{{{FRONT},status="ok"}}[$__range]))',
            "{{product_id}}",
            unit="short",
        ),
    ]
    return dash(
        "orbit-shop-sales",
        "Orbit Shop — Sales",
        "Shop admin view: revenue, conversion, mix, and who is buying.",
        panels,
        ["orbit-shop", "sales"],
    )


def catalog():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Catalog & inventory\nLive stock on the API. Telescopes start with only 6 units and get restocked slowly — they go red on purpose.",
        ),
        stat(
            2,
            "SKUs in catalog",
            0,
            3,
            4,
            4,
            f'count(shop_inventory_ratio{{{API}}})',
            unit="short",
            color="blue",
            spark=False,
        ),
        stat(
            3,
            "Units on hand",
            4,
            3,
            4,
            4,
            f'sum(shop_inventory_ratio{{{API}}})',
            unit="short",
            color="green",
            spark=False,
        ),
        stat(
            4,
            "SKUs at risk (<5)",
            8,
            3,
            4,
            4,
            f'count(shop_inventory_ratio{{{API}}} < 5)',
            unit="short",
            color="red",
            spark=False,
            desc="Products with fewer than 5 units",
        ),
        stat(
            5,
            "Product page views",
            12,
            3,
            6,
            4,
            f'sum(increase(shop_catalog_views_total{{{API}}}[$__range]))',
            unit="short",
            color="purple",
        ),
        stat(
            6,
            "View → buy",
            18,
            3,
            6,
            4,
            f'sum(increase(shop_orders_total{{{FRONT},status="ok"}}[$__range])) / clamp_min(sum(increase(shop_catalog_views_total{{{API}}}[$__range])), 1)',
            unit="percentunit",
            color="orange",
            desc="Paid orders / product detail views",
        ),
        gauge(
            7,
            "Stock by SKU",
            0,
            7,
            12,
            10,
            f'shop_inventory_ratio{{{API}}}',
            "{{product_id}}",
            unit="short",
            maxv=80,
        ),
        bargauge(
            8,
            "Units remaining",
            12,
            7,
            12,
            10,
            f'shop_inventory_ratio{{{API}}}',
            "{{product_id}}",
            unit="short",
            maxv=80,
        ),
        timeseries(
            9,
            "Inventory over time",
            0,
            17,
            14,
            8,
            f'shop_inventory_ratio{{{API}}}',
            "{{product_id}}",
            unit="short",
        ),
        bargauge(
            10,
            "Product page views",
            14,
            17,
            10,
            8,
            f'sum by (product_id) (increase(shop_catalog_views_total{{{API}}}[$__range]))',
            "{{product_id}}",
            unit="short",
        ),
        timeseries(
            11,
            "Views vs purchases",
            0,
            25,
            24,
            8,
            f'sum by (product_id) (rate(shop_catalog_views_total{{{API}}}[5m]))',
            "{{product_id}} views",
            unit="ops",
        ),
        logs(
            12,
            "Stock & restock logs",
            0,
            33,
            24,
            10,
            '{service_namespace="orbit-shop", service_name="shop-api"} |~ "(?i)stock|reserved|released|restock|inventory"',
        ),
    ]
    # add purchases as second target on panel 11
    panels[10]["targets"].append(
        target(
            f'sum by (product_id) (rate(shop_orders_total{{{FRONT},status="ok"}}[5m]))',
            "{{product_id}} paid",
            ref="B",
        )
    )
    return dash(
        "orbit-shop-catalog",
        "Orbit Shop — Catalog",
        "Inventory, low-stock, and which products people actually look at.",
        panels,
        ["orbit-shop", "catalog", "inventory"],
    )


def checkout():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Checkout & payments\nFunnel from browse → product → checkout → paid. Failures are tagged `card_declined`, `out_of_stock`, or `backend_timeout`.",
        ),
        stat(
            2,
            "1. Browse",
            0,
            3,
            5,
            5,
            f'sum(increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/products"}}[$__range]))',
            unit="short",
            color="blue",
        ),
        stat(
            3,
            "2. Product pages",
            5,
            3,
            5,
            5,
            f'sum(increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/products/{{product_id}}"}}[$__range]))',
            unit="short",
            color="purple",
        ),
        stat(
            4,
            "3. Checkout attempts",
            10,
            3,
            5,
            5,
            f'sum(increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/checkout"}}[$__range]))',
            unit="short",
            color="orange",
        ),
        stat(
            5,
            "4. Paid",
            15,
            3,
            5,
            5,
            f'sum(increase(shop_orders_total{{{FRONT},status="ok"}}[$__range]))',
            unit="short",
            color="green",
        ),
        stat(
            6,
            "Pay success",
            20,
            3,
            4,
            5,
            f'sum(increase(shop_payments_total{{{WORKER},status="authorized"}}[$__range])) / clamp_min(sum(increase(shop_payments_total{{{WORKER}}}[$__range])), 1)',
            unit="percentunit",
            color="green",
            desc="OrbitPay authorization rate",
        ),
        bargauge(
            7,
            "Why checkouts fail",
            0,
            8,
            12,
            8,
            f'sum by (reason) (increase(shop_orders_total{{{FRONT},status="failed"}}[$__range]))',
            "{{reason}}",
            unit="short",
        ),
        pie(
            8,
            "Checkout HTTP status",
            12,
            8,
            12,
            8,
            f'sum by (http_status_code) (increase(http_server_duration_milliseconds_count{{{FRONT},http_target="/api/checkout"}}[$__range]))',
            "{{http_status_code}}",
            desc="200 paid · 402 declined · 409 out of stock · 503 timeout",
        ),
        timeseries(
            9,
            "Failure reasons over time",
            0,
            16,
            14,
            8,
            f'sum by (reason) (rate(shop_orders_total{{{FRONT},status="failed"}}[5m]))',
            "{{reason}}",
            unit="ops",
            stacked=True,
        ),
        timeseries(
            10,
            "Checkout latency p95",
            14,
            16,
            10,
            8,
            f'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{FRONT},http_target="/api/checkout"}}[5m])))',
            "p95",
            unit="ms",
        ),
        timeseries(
            11,
            "OrbitPay authorized vs declined",
            0,
            24,
            12,
            8,
            f'sum by (status) (rate(shop_payments_total{{{WORKER}}}[5m]))',
            "{{status}}",
            unit="ops",
        ),
        bargauge(
            12,
            "Declines by SKU",
            12,
            24,
            12,
            8,
            f'sum by (product_id) (increase(shop_payments_total{{{WORKER},status="declined"}}[$__range]))',
            "{{product_id}}",
            unit="short",
            desc="Telescopes are expensive and decline more often",
        ),
        logs(
            13,
            "Failed checkouts & declines",
            0,
            32,
            24,
            10,
            '{service_namespace="orbit-shop"} |~ "(?i)declined|out of stock|checkout failed|timeout|card"',
        ),
    ]
    return dash(
        "orbit-shop-checkout",
        "Orbit Shop — Checkout",
        "Funnel, payment declines, stockouts, and checkout latency.",
        panels,
        ["orbit-shop", "checkout", "payments"],
    )


def fulfillment():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Fulfillment\nAfter a card is authorized the worker prints a shipping label (`orbitransit`) and queues a notification. The label printer is offline ~4% of the time.",
        ),
        stat(
            2,
            "Labels printed",
            0,
            3,
            6,
            5,
            f'sum(increase(shop_shipments_total{{{WORKER},status="ok"}}[$__range]))',
            unit="short",
            color="green",
        ),
        stat(
            3,
            "Label failures",
            6,
            3,
            6,
            5,
            f'sum(increase(shop_shipments_total{{{WORKER},status="failed"}}[$__range]))',
            unit="short",
            color="red",
        ),
        stat(
            4,
            "Ship success",
            12,
            3,
            6,
            5,
            f'sum(increase(shop_shipments_total{{{WORKER},status="ok"}}[$__range])) / clamp_min(sum(increase(shop_shipments_total{{{WORKER}}}[$__range])), 1)',
            unit="percentunit",
            color="blue",
        ),
        stat(
            5,
            "Pay → ship drop",
            18,
            3,
            6,
            5,
            f'1 - (sum(increase(shop_shipments_total{{{WORKER},status="ok"}}[$__range])) / clamp_min(sum(increase(shop_payments_total{{{WORKER},status="authorized"}}[$__range])), 1))',
            unit="percentunit",
            color="orange",
            desc="Authorized payments that did not get a label",
        ),
        timeseries(
            6,
            "Pay / ship / notify",
            0,
            8,
            16,
            9,
            f'sum by (http_target) (rate(http_server_duration_milliseconds_count{{{WORKER},http_target=~"/pay|/ship|/notify"}}[5m]))',
            "{{http_target}}",
            unit="ops",
        ),
        pie(
            7,
            "Worker HTTP status",
            16,
            8,
            8,
            9,
            f'sum by (http_status_code) (increase(http_server_duration_milliseconds_count{{{WORKER}}}[$__range]))',
            "{{http_status_code}}",
        ),
        timeseries(
            8,
            "Worker latency p95",
            0,
            17,
            12,
            8,
            f'histogram_quantile(0.95, sum by (http_target, le) (rate(http_server_duration_milliseconds_bucket{{{WORKER}}}[5m])))',
            "{{http_target}}",
            unit="ms",
        ),
        bargauge(
            9,
            "Labels by SKU",
            12,
            17,
            12,
            8,
            f'sum by (product_id) (increase(shop_shipments_total{{{WORKER},status="ok"}}[$__range]))',
            "{{product_id}}",
            unit="short",
        ),
        logs(
            10,
            "Shipping & payment worker logs",
            0,
            25,
            24,
            11,
            '{service_namespace="orbit-shop", service_name="shop-worker"} |~ "(?i)shipment|payment|notified|printer|declined|authorized"',
        ),
    ]
    return dash(
        "orbit-shop-fulfillment",
        "Orbit Shop — Fulfillment",
        "Payments that made it, shipping labels, and the flaky printer.",
        panels,
        ["orbit-shop", "fulfillment", "shipping"],
    )


def golden_signals():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Golden signals\nRate, errors, duration, saturation for the shop processes. Use the **Service** dropdown. Business numbers live under the Business folder.",
        ),
        stat(
            2,
            "RPS",
            0,
            3,
            4,
            5,
            f'sum(rate(http_server_duration_milliseconds_count{{{SVC}}}[$__rate_interval]))',
            unit="reqps",
            color="blue",
        ),
        stat(
            3,
            "Error rate",
            4,
            3,
            4,
            5,
            f'sum(rate(http_server_duration_milliseconds_count{{{SVC},http_status_code=~"[45].."}}[$__rate_interval])) / clamp_min(sum(rate(http_server_duration_milliseconds_count{{{SVC}}}[$__rate_interval])), 0.001)',
            unit="percentunit",
            color="red",
        ),
        stat(
            4,
            "p95",
            8,
            3,
            4,
            5,
            f'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[$__rate_interval])))',
            unit="ms",
            color="orange",
        ),
        stat(
            5,
            "p99",
            12,
            3,
            4,
            5,
            f'histogram_quantile(0.99, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[$__rate_interval])))',
            unit="ms",
            color="purple",
        ),
        stat(
            6,
            "In-flight",
            16,
            3,
            4,
            5,
            f'sum(http_server_active_requests{{{SVC}}})',
            unit="short",
            color="yellow",
        ),
        stat(
            7,
            "CPU",
            20,
            3,
            4,
            5,
            f'avg(process_cpu_utilization_ratio{{{SVC}}})',
            unit="percentunit",
            color="green",
        ),
        timeseries(
            8,
            "Request rate",
            0,
            8,
            8,
            8,
            f'sum by (service_name) (rate(http_server_duration_milliseconds_count{{{SVC}}}[5m]))',
            "{{service_name}}",
            unit="reqps",
        ),
        timeseries(
            9,
            "Error rate",
            8,
            8,
            8,
            8,
            f'sum by (service_name) (rate(http_server_duration_milliseconds_count{{{SVC},http_status_code=~"[45].."}}[5m])) / clamp_min(sum by (service_name) (rate(http_server_duration_milliseconds_count{{{SVC}}}[5m])), 0.001)',
            "{{service_name}}",
            unit="percentunit",
        ),
        multi_ts(
            10,
            "Latency",
            16,
            8,
            8,
            8,
            [
                (
                    f'histogram_quantile(0.50, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[5m])))',
                    "p50",
                ),
                (
                    f'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[5m])))',
                    "p95",
                ),
                (
                    f'histogram_quantile(0.99, sum by (le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[5m])))',
                    "p99",
                ),
            ],
            unit="ms",
        ),
        heatmap(
            11,
            "Latency heatmap",
            0,
            16,
            12,
            9,
            f'sum by (le) (increase(http_server_duration_milliseconds_bucket{{{SVC}}}[$__rate_interval]))',
        ),
        timeseries(
            12,
            "Status codes",
            12,
            16,
            12,
            9,
            f'sum by (http_status_code) (rate(http_server_duration_milliseconds_count{{{SVC}}}[5m]))',
            "{{http_status_code}}",
            unit="reqps",
            stacked=True,
        ),
        timeseries(
            13,
            "Saturation — RSS",
            0,
            25,
            12,
            8,
            f'process_resident_memory_bytes{{{SVC}}}',
            "{{service_name}}",
            unit="bytes",
        ),
        timeseries(
            14,
            "Saturation — in-flight requests",
            12,
            25,
            12,
            8,
            f'sum by (service_name) (http_server_active_requests{{{SVC}}})',
            "{{service_name}}",
            unit="short",
        ),
        logs(
            15,
            "Errors & warnings",
            0,
            33,
            24,
            10,
            '{service_namespace="orbit-shop", service_name=~"$service"} | detected_level =~ "error|warn|fatal"',
        ),
    ]
    return dash(
        "orbit-shop-red",
        "Golden signals",
        "Rate, errors, duration, saturation for Orbit Shop.",
        panels,
        ["orbit-shop", "technical", "red"],
        links=TECH_LINKS,
        templating=[service_var()],
    )


def http_dash():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### HTTP\nServer routes plus outbound client calls (`requests` instrumentation). Filter with **Service**.",
        ),
        timeseries(
            2,
            "Rate by route",
            0,
            3,
            12,
            9,
            f'sum by (http_target, http_method) (rate(http_server_duration_milliseconds_count{{{SVC}}}[5m]))',
            "{{http_method}} {{http_target}}",
            unit="reqps",
        ),
        timeseries(
            3,
            "p95 by route",
            12,
            3,
            12,
            9,
            f'histogram_quantile(0.95, sum by (http_target, le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[5m])))',
            "{{http_target}}",
            unit="ms",
        ),
        timeseries(
            4,
            "Rate by status",
            0,
            12,
            8,
            8,
            f'sum by (http_status_code) (rate(http_server_duration_milliseconds_count{{{SVC}}}[5m]))',
            "{{http_status_code}}",
            unit="reqps",
            stacked=True,
        ),
        timeseries(
            5,
            "Outbound client p95",
            8,
            12,
            8,
            8,
            f'histogram_quantile(0.95, sum by (http_method, le) (rate(http_client_duration_milliseconds_bucket{{{SVC}}}[5m])))',
            "{{http_method}}",
            unit="ms",
            desc="HTTP client spans from shop-frontend → api/worker",
        ),
        timeseries(
            6,
            "Request body size p95",
            16,
            12,
            8,
            8,
            f'histogram_quantile(0.95, sum by (le) (rate(http_server_request_size_bytes_bucket{{{SVC}}}[5m])))',
            "p95",
            unit="bytes",
        ),
        bargauge(
            7,
            "Top routes (requests in range)",
            0,
            20,
            12,
            9,
            f'sum by (http_target) (increase(http_server_duration_milliseconds_count{{{SVC}}}[$__range]))',
            "{{http_target}}",
            unit="short",
        ),
        bargauge(
            8,
            "Slowest routes (p95)",
            12,
            20,
            12,
            9,
            f'histogram_quantile(0.95, sum by (http_target, le) (rate(http_server_duration_milliseconds_bucket{{{SVC}}}[5m])))',
            "{{http_target}}",
            unit="ms",
        ),
        timeseries(
            9,
            "4xx / 5xx by route",
            0,
            29,
            24,
            8,
            f'sum by (http_target, http_status_code) (rate(http_server_duration_milliseconds_count{{{SVC},http_status_code=~"[45].."}}[5m]))',
            "{{http_status_code}} {{http_target}}",
            unit="reqps",
        ),
    ]
    return dash(
        "orbit-shop-http",
        "HTTP",
        "Per-route server and client HTTP telemetry.",
        panels,
        ["orbit-shop", "technical", "http"],
        links=TECH_LINKS,
        templating=[service_var()],
    )


def traces_dash():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Traces\nSpan metrics and the service graph, generated by Tempo from OTLP spans. Open a slow/error trace in Explore → Tempo.",
        ),
        timeseries(
            2,
            "Span rate",
            0,
            3,
            12,
            8,
            f'sum by (service) (rate(traces_spanmetrics_calls_total{{{SPAN_SVC}}}[5m]))',
            "{{service}}",
            unit="ops",
        ),
        timeseries(
            3,
            "Error spans",
            12,
            3,
            12,
            8,
            f'sum by (service, span_name) (rate(traces_spanmetrics_calls_total{{{SPAN_SVC},status_code="STATUS_CODE_ERROR"}}[5m]))',
            "{{service}} {{span_name}}",
            unit="ops",
        ),
        timeseries(
            4,
            "Span p95 by name",
            0,
            11,
            12,
            8,
            f'histogram_quantile(0.95, sum by (span_name, le) (rate(traces_spanmetrics_latency_bucket{{{SPAN_SVC},span_kind="SPAN_KIND_SERVER"}}[5m])))',
            "{{span_name}}",
            unit="s",
            desc="Tempo spanmetrics latency is in seconds",
        ),
        timeseries(
            5,
            "Service graph edges",
            12,
            11,
            12,
            8,
            f'sum by (client, server) (rate(traces_service_graph_request_total[5m]))',
            "{{client}} → {{server}}",
            unit="ops",
        ),
        timeseries(
            6,
            "Failed edges",
            0,
            19,
            12,
            8,
            f'sum by (client, server) (rate(traces_service_graph_request_failed_total[5m]))',
            "{{client}} → {{server}}",
            unit="ops",
        ),
        timeseries(
            7,
            "Edge latency p95 (server)",
            12,
            19,
            12,
            8,
            f'histogram_quantile(0.95, sum by (client, server, le) (rate(traces_service_graph_request_server_seconds_bucket[5m])))',
            "{{client}} → {{server}}",
            unit="s",
        ),
        bargauge(
            8,
            "Busiest spans",
            0,
            27,
            12,
            8,
            f'sum by (span_name) (increase(traces_spanmetrics_calls_total{{{SPAN_SVC}}}[$__range]))',
            "{{span_name}}",
            unit="short",
        ),
        pie(
            9,
            "Span kind mix",
            12,
            27,
            12,
            8,
            f'sum by (span_kind) (increase(traces_spanmetrics_calls_total{{{SPAN_SVC}}}[$__range]))',
            "{{span_kind}}",
        ),
        logs(
            10,
            "Logs with a trace_id (click through to Tempo)",
            0,
            35,
            24,
            10,
            '{service_namespace="orbit-shop", service_name=~"$service"} | trace_id != ""',
        ),
    ]
    return dash(
        "orbit-shop-traces",
        "Traces",
        "Tempo spanmetrics, service graph, and trace-correlated logs.",
        panels,
        ["orbit-shop", "technical", "traces"],
        links=TECH_LINKS,
        templating=[service_var()],
    )


def logs_dash():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Logs\nOTLP logs in Loki. `detected_level` comes from the collector; `trace_id` is on the line for jumping into Tempo.",
        ),
        loki_ts(
            2,
            "Log rate by service",
            0,
            3,
            12,
            8,
            'sum by (service_name) (count_over_time({service_namespace="orbit-shop", service_name=~"$service"}[1m]))',
            "{{service_name}}",
            unit="ops",
        ),
        loki_ts(
            3,
            "Log rate by level",
            12,
            3,
            12,
            8,
            'sum by (detected_level) (count_over_time({service_namespace="orbit-shop", service_name=~"$service"}[1m]))',
            "{{detected_level}}",
            unit="ops",
        ),
        logs(
            4,
            "Errors",
            0,
            11,
            24,
            10,
            '{service_namespace="orbit-shop", service_name=~"$service"} | detected_level = "error"',
        ),
        logs(
            5,
            "Warnings",
            0,
            21,
            24,
            9,
            '{service_namespace="orbit-shop", service_name=~"$service"} | detected_level = "warn"',
        ),
        logs(
            6,
            "All logs",
            0,
            30,
            24,
            10,
            '{service_namespace="orbit-shop", service_name=~"$service"}',
        ),
    ]
    return dash(
        "orbit-shop-logs",
        "Logs",
        "Log volume, levels, and the error stream.",
        panels,
        ["orbit-shop", "technical", "logs"],
        links=TECH_LINKS,
        templating=[service_var()],
    )


def runtime_dash():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Runtime\nOpenTelemetry system metrics from the shop processes (CPython).",
        ),
        timeseries(
            2,
            "CPU utilization",
            0,
            3,
            12,
            8,
            f'process_cpu_utilization_ratio{{{SVC}}}',
            "{{service_name}}",
            unit="percentunit",
        ),
        timeseries(
            3,
            "Resident memory",
            12,
            3,
            12,
            8,
            f'process_resident_memory_bytes{{{SVC}}}',
            "{{service_name}}",
            unit="bytes",
        ),
        timeseries(
            4,
            "Threads",
            0,
            11,
            8,
            8,
            f'process_thread_count{{{SVC}}}',
            "{{service_name}}",
            unit="short",
        ),
        timeseries(
            5,
            "Open FDs",
            8,
            11,
            8,
            8,
            f'process_open_fds{{{SVC}}}',
            "{{service_name}}",
            unit="short",
        ),
        timeseries(
            6,
            "CPython GC",
            16,
            11,
            8,
            8,
            f'sum by (service_name) (rate(process_runtime_cpython_gc_count_bytes_total{{{SVC}}}[5m]))',
            "{{service_name}}",
            unit="ops",
        ),
        timeseries(
            7,
            "Network receive",
            0,
            19,
            12,
            8,
            f'rate(process_network_receive_bytes_total{{{SVC}}}[5m])',
            "{{service_name}}",
            unit="Bps",
        ),
        timeseries(
            8,
            "Network transmit",
            12,
            19,
            12,
            8,
            f'rate(process_network_transmit_bytes_total{{{SVC}}}[5m])',
            "{{service_name}}",
            unit="Bps",
        ),
        timeseries(
            9,
            "Process uptime",
            0,
            27,
            24,
            7,
            f'time() - process_start_time_seconds{{{SVC}}}',
            "{{service_name}}",
            unit="s",
        ),
    ]
    return dash(
        "orbit-shop-runtime",
        "Runtime",
        "CPU, memory, FDs, GC, and network for shop processes.",
        panels,
        ["orbit-shop", "technical", "runtime"],
        links=TECH_LINKS,
        templating=[service_var()],
    )


def stack_dash():
    panels = [
        text(
            1,
            "",
            0,
            0,
            24,
            3,
            "### Obs stack\nPrometheus scrape of Grafana, Loki, Tempo, and the OTel collector. Shop app telemetry is on the other Technical dashboards.",
        ),
        stat(
            2,
            "Targets up",
            0,
            3,
            4,
            4,
            'sum(up{job=~"prometheus|loki|tempo|grafana|otel-collector"})',
            unit="short",
            color="green",
            spark=False,
        ),
        stat(
            3,
            "Targets down",
            4,
            3,
            4,
            4,
            'sum(up{job=~"prometheus|loki|tempo|grafana|otel-collector"} == 0)',
            unit="short",
            color="red",
            spark=False,
        ),
        timeseries(
            4,
            "Target health",
            8,
            3,
            16,
            4,
            'up{job=~"prometheus|loki|tempo|grafana|otel-collector"}',
            "{{job}}",
            unit="short",
        ),
        timeseries(
            5,
            "Collector accepted spans",
            0,
            7,
            8,
            8,
            'sum(rate(otelcol_receiver_accepted_spans[5m]))',
            "accepted",
            unit="ops",
        ),
        timeseries(
            6,
            "Collector accepted metrics",
            8,
            7,
            8,
            8,
            'sum(rate(otelcol_receiver_accepted_metric_points[5m]))',
            "accepted",
            unit="ops",
        ),
        timeseries(
            7,
            "Collector accepted logs",
            16,
            7,
            8,
            8,
            'sum(rate(otelcol_receiver_accepted_log_records[5m]))',
            "accepted",
            unit="ops",
        ),
        timeseries(
            8,
            "Collector refused / failed",
            0,
            15,
            12,
            8,
            'sum by (__name__) (rate(otelcol_receiver_refused_spans[5m]) or rate(otelcol_receiver_failed_spans[5m]) or rate(otelcol_receiver_refused_metric_points[5m]) or rate(otelcol_receiver_failed_metric_points[5m]) or rate(otelcol_receiver_refused_log_records[5m]) or rate(otelcol_receiver_failed_log_records[5m]))',
            "{{__name__}}",
            unit="ops",
        ),
        timeseries(
            9,
            "Tempo spans received",
            12,
            15,
            12,
            8,
            'sum(rate(tempo_distributor_spans_received_total[5m]))',
            "spans",
            unit="ops",
        ),
        timeseries(
            10,
            "Loki request rate",
            0,
            23,
            12,
            8,
            'sum by (route, status_code) (rate(loki_request_duration_seconds_count[5m]))',
            "{{status_code}} {{route}}",
            unit="reqps",
        ),
        timeseries(
            11,
            "Stack RSS",
            12,
            23,
            12,
            8,
            'process_resident_memory_bytes{job=~"prometheus|loki|tempo|grafana|otel-collector"}',
            "{{job}}",
            unit="bytes",
        ),
        timeseries(
            12,
            "Scrape duration",
            0,
            31,
            24,
            7,
            'scrape_duration_seconds{job=~"prometheus|loki|tempo|grafana|otel-collector"}',
            "{{job}}",
            unit="s",
        ),
    ]
    return dash(
        "orbit-shop-stack",
        "Obs stack",
        "Health of Grafana, Loki, Tempo, Prometheus, and the collector.",
        panels,
        ["orbit-shop", "technical", "stack"],
        links=TECH_LINKS,
    )


def main():
    root = Path(__file__).resolve().parent
    business = root / "Business"
    technical = root / "Technical"
    business.mkdir(exist_ok=True)
    technical.mkdir(exist_ok=True)

    files = {
        business / "sales.json": sales(),
        business / "catalog.json": catalog(),
        business / "checkout.json": checkout(),
        business / "fulfillment.json": fulfillment(),
        technical / "golden-signals.json": golden_signals(),
        technical / "http.json": http_dash(),
        technical / "traces.json": traces_dash(),
        technical / "logs.json": logs_dash(),
        technical / "runtime.json": runtime_dash(),
        technical / "stack.json": stack_dash(),
    }
    for path, payload in files.items():
        path.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {path.relative_to(root)} ({len(payload['panels'])} panels)")

    for stale in root.glob("*.json"):
        stale.unlink()
        print(f"removed leftover {stale.name}")


if __name__ == "__main__":
    main()
