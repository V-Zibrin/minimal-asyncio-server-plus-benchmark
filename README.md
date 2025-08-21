# Minimal Async HTTP Server + Benchmark (Python, stdlib-only)

A tiny **async HTTP server** plus a **performance benchmark** written in **pure Python 3** (no third-party deps). Built to satisfy a test task:

- Standard library only
- Platform-independent
- Serve multiple clients concurrently
- Keep the server **as small as possible**
- **Measure and present** performance

---

## Project structure

```
.
├── minimal_server.py      # Minimal asyncio HTTP server
├── bench_core.py          # Core benchmarking logic (closed/open/sweep/preset)
├── bench.py               # Tiny CLI wrapper
├── bench_config.json      # Optional presets (smoke/standard/stress)
└── README.md
```

**Python:** 3.8+  
**Dependencies:** none (stdlib only)

---

## 1) Minimal server

`minimal_server.py` is a ~40-line HTTP/1.1 server using `asyncio`.  
It accepts many concurrent connections, reads headers (with a short timeout), responds `200 OK`, and closes.

Run:

```bash
python3 async_server_tiny.py --host 127.0.0.1 --port 8000
```

---

## 2) Benchmark CLI

All commands target a URL (default `http://127.0.0.1:8000/`).

### Closed-loop (`closed`)
Fixed **N** requests with concurrency **C**. Reports throughput (req/s) and latency percentiles.

```bash
python3 bench.py closed -n 5000 -c 200 --repeat 3 --warmup 500
```

### Open-loop (`open`)
Launch requests at a **target RPS** for **D** seconds, regardless of completion (arrival-process driven).

```bash
python3 bench.py open --rps 3000 --duration 15 --concurrency 800 --repeat 3 --warmup-sec 5
```

### Sweep (`sweep`)
Closed-loop across multiple concurrencies (medians only). Useful to find the “knee”.

```bash
python3 bench.py sweep -n 3000 --concurrencies 1,2,5,10,20,50,100,200 --repeat 3 --warmup 300
```

### Preset suite (`preset`)
Calibration sweep (closed-loop) → open-loop runs at ~50%, ~90%, and ~110% of calibrated capacity.

Presets:
- **smoke** — quick sanity
- **standard** — presentation-ready
- **stress** — push hard to observe degradation

```bash
python3 bench.py --config bench_config.json preset --profile standard
```

> The preset also writes a CSV (`preset_<profile>_<timestamp>.csv`) with all results (sweep + open-loop).

---

## 3) Configuration (optional)

`bench_config.json` overrides preset parameters (concurrencies, totals, duration, repeats, warmups, etc.).

```json
{
  "presets": {
    "smoke": {
      "closed": { "concurrencies": [1, 10, 50, 100], "total_per_c": 1000, "warmup": 200, "repeat": 2 },
      "open":   { "duration": 8.0, "warmup_sec": 3.0 }
    },
    "standard": {
      "closed": { "concurrencies": [1, 2, 5, 10, 20, 50, 100, 200, 400], "total_per_c": 5000, "warmup": 1000, "repeat": 3 },
      "open":   { "duration": 15.0, "warmup_sec": 5.0 }
    },
    "stress": {
      "closed": { "concurrencies": [100, 200, 400, 800, 1200], "total_per_c": 15000, "warmup": 2000, "repeat": 3 },
      "open":   { "duration": 25.0, "warmup_sec": 8.0 }
    }
  }
}
```

> Tip: Make the **open-loop concurrency cap** configurable here if you plan to test on very large servers.

---

## 4) CSV output

Running `preset` produces a single CSV with both phases:

- **closed_sweep** rows: per-concurrency medians (throughput & latency percentiles)
- **open_loop** rows: target RPS, achieved RPS, latency percentiles, errors

A run-level timestamp is included as a **batch marker** (so all rows from one run share the same timestamp). This helps group/compare multiple runs.

---

## 5) Design choices (brief)

- **Server:** intentionally tiny; responds with valid HTTP and closes. Fits the “less code, the better” goal.
- **Closed-loop vs Open-loop:** both are provided. Closed-loop measures capacity under backpressure; open-loop probes stability at and above capacity.
- **Calibration:** `preset` first sweeps concurrency, picks the best by **median throughput** (robust to noise), then tests open-loop at ≈50%, ≈90%, ≈110% of that rate to show underload, near-knee, and slight overload behavior.
- **Safety guards:** open-loop uses a semaphore + small backlog limit to avoid unbounded task growth in the client.

---

## 6) Example workflow

```bash
# 1) Start the server
python3 minimal_server.py --host 127.0.0.1 --port 8000

# 2) Quick sanity
python3 bench.py --config bench_config.json preset --profile smoke

# 3) Presentation-ready suite
python3 bench.py --config bench_config.json preset --profile standard

# 4) Ad-hoc experiments
python3 bench.py sweep -n 2000 --concurrencies 10,50,100,200 --repeat 3 --warmup 200
python3 bench.py open --rps 5000 --duration 20 --concurrency 1200 --repeat 3 --warmup-sec 5
```
or (quickest)
```bash
# Starts ther server on 127.0.0.1:8000 by default
python3 minimal_server.py

# Launches benchmark in preset mode with default config file and standard profile
python3 bench.py preset
```

---

## 7) Notes & limitations

- The server does **not** parse full HTTP requests (by design). It returns a fixed `200 OK`.
- The benchmark uses new TCP connections per request (simple and portable).
- For very high throughputs or very large concurrencies, consider:
  - Raising OS file-descriptor limits (`ulimit -n`)
  - Adjusting the **open-loop concurrency cap**
  - Running client and server on separate machines to avoid local resource contention
