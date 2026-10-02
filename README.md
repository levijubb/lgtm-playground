# grafana-playground

A local Grafana LGTM lab: Prometheus, Loki, Tempo, and Grafana, fed by a small multi-service demo called Orbit Shop. One Compose project.

## Start

```bash
cp .env.example .env   # optional; ports default to 127.0.0.1
docker compose up -d --build
```

Give the load generator a minute so the dashboards have something to draw.

|            |                                              |
| ---------- | -------------------------------------------- |
| Grafana    | http://127.0.0.1:3000 (`admin` / `changeme`) |
| Orbit Shop | http://127.0.0.1:8081                        |
| Prometheus | http://127.0.0.1:9090                        |
| Loki       | http://127.0.0.1:3100                        |

OTLP from the host is `127.0.0.1:4317` (gRPC) and `127.0.0.1:4318` (HTTP). Nothing in front of the collector authenticates callers.

To open Grafana and the shop from another machine, set `BIND_ADDR` in `.env` to this host's address and run `docker compose up -d` again. Prometheus and Loki stay on `127.0.0.1` either way. Do not point `BIND_ADDR` at an address you do not trust: the OTLP receiver is open, and the Grafana password is `changeme`.

The shop's **Open Grafana** button uses the same hostname you used to open the shop, on port 3000. Dashboard **Shop UI** links point at `http://127.0.0.1:8081/`. If you browse Grafana from another machine, open port 8081 on that same host, or change the URL in `dashboards/_build.py` and regenerate.

## What is running

Orbit Shop is one image and four processes, selected with `SHOP_ROLE`:

- `shop-frontend` — the UI, and the call that ties a checkout together (`:8081`)
- `shop-api` — catalog, inventory, payment
- `shop-worker` — shipment labels
- `shop-loadgen` — steady background traffic, plus the buttons on the shop page for slow calls, errors, and bursts

Each process exports traces, metrics, and logs with OTLP HTTP to the collector. The collector writes traces to Tempo, metrics to Prometheus remote-write, and logs to Loki. Grafana is provisioned with those three datasources linked to each other (exemplars, trace-to-logs, service graph). Tempo also remote-writes span metrics and service graphs to Prometheus.

Dashboards are file-provisioned from `dashboards/Business` and `dashboards/Technical`.

## Dashboards

`dashboards/_build.py` is the source. The JSON beside it is what Grafana loads, so a clone does not need to run the generator to start. After editing the generator:

```bash
python3 dashboards/_build.py
```

Grafana picks up file changes within about 15 seconds.

## Stop and reset

```bash
docker compose down       # stop, keep data
docker compose down -v    # also delete Prometheus, Loki, Tempo, and Grafana volumes
```

## What this is not

Single node, local disk, Loki has auth disabled, the Grafana password is the default above, and OTLP is unauthenticated. Image tags are pinned to the versions this playground was run with:

| Image                                  | Tag         |
| -------------------------------------- | ----------- |
| `grafana/grafana`                      | `13.2.1`    |
| `prom/prometheus`                      | `v3.14.0`   |
| `grafana/loki`                         | `3.7.7`     |
| `grafana/tempo`                        | `3.0.0`     |
| `otel/opentelemetry-collector-contrib` | `0.160.0`   |
| `busybox` (Tempo volume ownership)     | `1.37`      |
| `python` (shop image)                  | `3.12-slim` |
