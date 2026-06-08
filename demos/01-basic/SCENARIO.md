# Demo 01 - Basic synthetic monitoring run

This demo defines three synthetic checks and runs them, then shows the
Prometheus export that a scrape target would expose.

## The check file

`checks.json` defines:

1. **homepage** - an HTTP `GET` that must return `200` and contain the
   substring `Example`, within a 800ms latency budget.
2. **api-health** - an HTTP `GET` against a JSON health endpoint that must
   return `200`.
3. **db-port** - a raw TCP connect to a Postgres port (reachability only).

## Run it

Human-readable table:

```sh
python -m probesite run demos/01-basic/checks.json
```

Machine-readable JSON (for piping into jq / dashboards):

```sh
python -m probesite run demos/01-basic/checks.json --format json
```

Prometheus text-format (point a Prometheus scrape job at a wrapper that
serves this output, or write it to the node_exporter textfile dir):

```sh
python -m probesite run demos/01-basic/checks.json --prometheus
```

## Exit codes

- `0` - every check is fully **up**.
- `1` - at least one check is **degraded** (assertion failed) or **down**.
- `2` - bad/missing check file.

This makes `probesite run` drop-in usable in CI or a cron-driven
blackbox-exporter replacement: a non-zero exit fires your alerting.

## Example Prometheus scrape integration

```
# crontab: write metrics to the textfile collector every minute
* * * * * python -m probesite run /etc/probesite/checks.json --prometheus \
            > /var/lib/node_exporter/textfile/probesite.prom.$$ \
          && mv /var/lib/node_exporter/textfile/probesite.prom.$$ \
                /var/lib/node_exporter/textfile/probesite.prom
```
