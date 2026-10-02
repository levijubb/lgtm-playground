# grafana-playground

A full app observability playground for logs, traces, and OpenTelemetry. It runs a local Grafana LGTM stack — Loki, Grafana, Tempo, and Prometheus — next to a small multi-service shop called Orbit Shop, so you can click through a real app and watch active telemetry, logs and errors.

## Start

```bash
cp .env.example .env   # optional; ports default to 127.0.0.1
docker compose up -d --build
```

Give the load generator about a minute. After that the dashboards have traffic to draw.

|            |                                              |
| ---------- | -------------------------------------------- |
| Grafana    | http://127.0.0.1:3000 (`admin` / `changeme`) |
| Orbit Shop | http://127.0.0.1:8081                        |
| Prometheus | http://127.0.0.1:9090                        |
| Loki       | http://127.0.0.1:3100                        |

You can also send your own OTLP to `127.0.0.1:4317` (gRPC) or `127.0.0.1:4318` (HTTP). Nothing in front of the collector authenticates callers.

## Tailscale

If you are running this on a server, set `BIND_ADDR` in `.env` to that machine's Tailscale IP. Grafana (`:3000`), Orbit Shop (`:8081`), and the OTLP receiver (`:4317` gRPC, `:4318` HTTP) then listen on the tailnet, so you can open them from your other devices without putting them on the public internet.

```bash
tailscale ip -4
```

Put the address it prints in `.env`:

```bash
BIND_ADDR=100.x.y.z
```

Then recreate the containers:

```bash
docker compose up -d
```

Prometheus and Loki stay on `127.0.0.1` either way. Only do this on a tailnet you trust: the collector still does not authenticate callers, and the Grafana password is `changeme`.

The shop's **Open Grafana** button uses the same hostname you used to open the shop, on port 3000. Dashboard **Shop UI** links point at `http://127.0.0.1:8081/`. If you browse Grafana from another machine, open port 8081 on that same host, or change the URL in `dashboards/_build.py` and regenerate.

## What is running

Orbit Shop is one image and four processes, picked with `SHOP_ROLE`:

- `shop-frontend` — the UI, and the call that ties a checkout together (`:8081`)
- `shop-api` — catalog, inventory, and payment
- `shop-worker` — shipment labels
- `shop-loadgen` — steady background traffic, plus buttons on the shop page for slow calls, errors, and bursts

Each process exports traces, metrics, and logs with OTLP HTTP to the collector. The collector writes traces to Tempo, metrics to Prometheus (remote write), and logs to Loki. Grafana starts with those three datasources already linked — exemplars, trace-to-logs, and the service graph. Tempo also remote-writes span metrics and service graphs to Prometheus.

Dashboards are provisioned from `dashboards/Business` and `dashboards/Technical`.

## Dashboards

`dashboards/_build.py` is the source of truth. The JSON next to it is what Grafana loads, so a fresh clone starts without running the generator. After you edit the generator:

```bash
python3 dashboards/_build.py
```

Grafana picks up file changes within about 15 seconds.

## Stop and reset

```bash
docker compose down       # stop, keep data
docker compose down -v    # also delete Prometheus, Loki, Tempo, and Grafana volumes
```
