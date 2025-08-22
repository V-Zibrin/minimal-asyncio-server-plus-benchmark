import asyncio
import csv
import time
from typing import Dict, List, Sequence, Tuple, Optional, Any
from urllib.parse import urlparse


# ---------- helpers ----------

def build_http_get(url: str) -> Tuple[str, int, bytes]:
    parsed_url = urlparse(url)
    if parsed_url.scheme and parsed_url.scheme.lower() != "http":
        raise ValueError("Only plain HTTP is supported")
    host = parsed_url.hostname or "127.0.0.1"
    port = parsed_url.port or 80
    path = parsed_url.path or "/"
    if parsed_url.query:
        path += "?" + parsed_url.query
    host_header = parsed_url.netloc or host
    request_bytes = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("ascii")
    return host, port, request_bytes


async def one_request(host: str, port: int, request_bytes: bytes, timeout: float) -> float:
    """Do one HTTP request over a new TCP connection; return latency seconds, or -1 on error."""
    start_time = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.write(request_bytes)
        await writer.drain()
        # Read until EOF (server closes)
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
            if not chunk:
                break
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return time.perf_counter() - start_time
    except Exception:
        return -1.0


def percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(  # ensure we don't go negative
        0,
        min(  # ensure we don't exceed the last index
            int(
                q * (len(sorted_values) - 1)
                + 0.5  # round to nearest index
            ),
            len(sorted_values) - 1
        )
    )
    return sorted_values[index]


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    length = len(values_sorted)
    middle = length // 2
    return values_sorted[middle] if length % 2 else 0.5 * (values_sorted[middle - 1] + values_sorted[middle])


def _summarize_latencies(latencies: List[float]) -> Dict[str, float]:
    latencies.sort()
    successful_requests = len(latencies)
    return {
        "successful_requests": successful_requests,
        "p50_ms": percentile(latencies, 0.5) * 1000 if successful_requests else 0.0,
        "p90_ms": percentile(latencies, 0.9) * 1000 if successful_requests else 0.0,
        "p99_ms": percentile(latencies, 0.99) * 1000 if successful_requests else 0.0,
        "min_ms": latencies[0] * 1000 if successful_requests else 0.0,
        "avg_ms": (sum(latencies) / successful_requests) * 1000 if successful_requests else 0.0,
        "max_ms": latencies[-1] * 1000 if successful_requests else 0.0,
    }


def print_detail_header_closed(url: str, total_requests: int, concurrency: int, error_count: int, wall_time: float,
                               throughput: float):
    print(f"URL: {url}")
    print(f"Total: {total_requests}, Concurrency: {concurrency}, Errors: {error_count}")
    print(f"Wall time: {wall_time:.3f}s, Throughput: {throughput:.1f} req/s")


def print_detail_header_open(url: str, target_rps: float, duration_sec: float, concurrency_cap: int, error_count: int,
                             wall_time: float, achieved_rps: float):
    print(f"URL: {url}")
    print(f"Mode: open-loop, Target: {target_rps:.1f} rps for {duration_sec:.1f}s, Concurrency cap: {concurrency_cap}")
    print(f"Wall time: {wall_time:.3f}s, Achieved: {achieved_rps:.1f} req/s, Errors: {error_count}")


def print_latencies(label: str, stats: Dict[str, float]):
    if stats["successful_requests"]:
        print(
            label,
            f"min={stats['min_ms']:.2f}ms",
            f"avg={stats['avg_ms']:.2f}ms",
            f"p50={stats['p50_ms']:.2f}ms",
            f"p90={stats['p90_ms']:.2f}ms",
            f"p99={stats['p99_ms']:.2f}ms",
            f"max={stats['max_ms']:.2f}ms",
        )


# ---------- closed-loop ----------

async def _closed_once(url: str, total_requests: int, concurrency: int, timeout: float, verbose: bool
                       ) -> Dict[str, float]:
    host, port, request_bytes = build_http_get(url)
    concurrency_semaphore = asyncio.Semaphore(concurrency)
    latencies: List[float] = []
    error_count = 0

    async def perform_request():
        nonlocal error_count
        async with concurrency_semaphore:
            duration = await one_request(host, port, request_bytes, timeout)
            if duration < 0:
                error_count += 1
            else:
                latencies.append(duration)

    start_time = time.perf_counter()
    await asyncio.gather(*(perform_request() for _ in range(total_requests)))
    wall_time = time.perf_counter() - start_time

    stats = _summarize_latencies(latencies)
    throughput = (stats["successful_requests"] / wall_time) if wall_time > 0 else 0.0
    if verbose:
        print_detail_header_closed(url, total_requests, concurrency, error_count, wall_time, throughput)
        print_latencies("Latency:", stats)
    return {**stats, "errors": error_count, "throughput": throughput, "wall": wall_time}


async def run_closed(url: str, total: int, concurrency: int, timeout: float, warmup: int, repeat: int, quiet: bool
                     ) -> Dict[str, float]:
    if warmup > 0:
        await _closed_once(url, warmup, concurrency, timeout, verbose=False)
    run_summaries = []
    for i in range(repeat):
        if not quiet:
            print(f"--- closed run {i + 1}/{repeat} ---")
        run_summaries.append(
            await _closed_once(url, total, concurrency, timeout, verbose=not quiet)
        )
    summary = {
        "throughput": median([r["throughput"] for r in run_summaries]),
        "p50_ms": median([r["p50_ms"] for r in run_summaries]),
        "p90_ms": median([r["p90_ms"] for r in run_summaries]),
        "p99_ms": median([r["p99_ms"] for r in run_summaries]),
        "errors": sum(r["errors"] for r in run_summaries) / max(repeat, 1),
    }
    if not quiet:
        print("=== closed summary (median) ===")
        print(f"Throughput: {summary['throughput']:.1f} req/s")
        print(f"Latency: p50={summary['p50_ms']:.2f}ms p90={summary['p90_ms']:.2f}ms p99={summary['p99_ms']:.2f}ms")
    return summary


# ---------- open-loop ----------

async def _open_once(url: str, target_rps: float, duration_sec: float, concurrency_cap: int, timeout: float,
                     verbose: bool) -> Dict[str, float]:
    host, port, request_bytes = build_http_get(url)
    concurrency_semaphore = asyncio.Semaphore(concurrency_cap)
    in_flight_tasks: set = set()
    latencies: List[float] = []
    error_count = 0

    async def perform_request():
        nonlocal error_count
        async with concurrency_semaphore:
            duration = await one_request(host, port, request_bytes, timeout)
            if duration < 0:
                error_count += 1
            else:
                latencies.append(duration)

    schedule_interval_seconds = 1.0 / max(target_rps, 1e-9)  # avoid division by zero
    start_time = time.perf_counter()
    next_scheduled_time = start_time
    while True:
        now = time.perf_counter()
        if now - start_time >= duration_sec:
            break
        if now >= next_scheduled_time and len(in_flight_tasks) < 4 * concurrency_cap:  # avoid too many tasks in flight
            task = asyncio.create_task(perform_request())
            in_flight_tasks.add(task)
            task.add_done_callback(in_flight_tasks.discard)
            next_scheduled_time += schedule_interval_seconds
        else:
            await asyncio.sleep(min(0.001, max(0.0, next_scheduled_time - now)))

    if in_flight_tasks:
        await asyncio.gather(*in_flight_tasks, return_exceptions=True)

    wall_time = time.perf_counter() - start_time
    stats = _summarize_latencies(latencies)
    achieved_rps = (stats["successful_requests"] / wall_time) if wall_time > 0 else 0.0
    if verbose:
        print_detail_header_open(url, target_rps, duration_sec, concurrency_cap, error_count, wall_time, achieved_rps)
        print_latencies("Latency:", stats)
    return {**stats, "errors": error_count, "throughput": achieved_rps, "wall": wall_time}


async def run_open(url: str, rps: float, duration: float, concurrency: int, timeout: float, warmup_sec: float,
                   repeat: int, quiet: bool) -> Dict[str, float]:
    if warmup_sec > 0:
        await _open_once(url, rps, warmup_sec, concurrency, timeout, verbose=False)
    run_summaries = []
    for i in range(repeat):
        if not quiet:
            print(f"--- open run {i + 1}/{repeat} ---")
        run_summaries.append(await _open_once(url, rps, duration, concurrency, timeout, verbose=not quiet))
    summary = {
        "throughput": median([r["throughput"] for r in run_summaries]),
        "p50_ms": median([r["p50_ms"] for r in run_summaries]),
        "p90_ms": median([r["p90_ms"] for r in run_summaries]),
        "p99_ms": median([r["p99_ms"] for r in run_summaries]),
        "errors": sum(r["errors"] for r in run_summaries) / max(repeat, 1),
    }
    if not quiet:
        print("=== open summary (median) ===")
        print(f"Achieved: {summary['throughput']:.1f} req/s")
        print(f"Latency: p50={summary['p50_ms']:.2f}ms p90={summary['p90_ms']:.2f}ms p99={summary['p99_ms']:.2f}ms")
    return summary


# ---------- sweep & preset ----------
async def run_sweep(url: str, total: int, concurrencies: Sequence[int], timeout: float, warmup: int, repeat: int,
                    quiet: bool = False) -> List[Tuple[int, Dict[str, float]]]:
    """
    Runs closed-loop medians across a list of concurrencies.
    Returns a list of (concurrency, summary) so callers (e.g. run_preset)
    can reuse the results instead of re-running.
    """
    results: List[Tuple[int, Dict[str, float]]] = []
    if not quiet:
        print("=== sweep (closed-loop medians) ===")
    for concurrency in concurrencies:
        summary = await run_closed(url, total, concurrency, timeout, warmup, repeat, quiet=True)
        results.append((concurrency, summary))
        if not quiet:
            print(
                f"c={concurrency:>4} -> thr={summary['throughput']:>8.1f} rps  "
                f"p50={summary['p50_ms']:>7.2f}ms  p90={summary['p90_ms']:>7.2f}ms  p99={summary['p99_ms']:>7.2f}ms"
            )
    return results


def _preset_defaults(profile: str) -> Dict[str, Dict[str, Any]]:
    if profile == "smoke":
        return {
            "closed": {"concurrencies": [1, 10, 50, 100], "total_per_c": 1000, "warmup": 200, "repeat": 2},
            "open": {"duration": 8.0, "warmup_sec": 3.0},
        }
    if profile == "stress":
        return {
            "closed": {"concurrencies": [100, 200, 400, 800, 1200], "total_per_c": 15000, "warmup": 2000, "repeat": 3},
            "open": {"duration": 25.0, "warmup_sec": 8.0},
        }
    # standard
    return {
        "closed": {"concurrencies": [1, 2, 5, 10, 20, 50, 100, 200, 400], "total_per_c": 5000, "warmup": 1000,
                   "repeat": 3},
        "open": {"duration": 15.0, "warmup_sec": 5.0},
    }


def _preset_from_config(profile: str, config: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    base = _preset_defaults(profile)
    if not config:
        return base
    presets = config.get("presets") or {}
    user = presets.get(profile) or {}
    merged = {"closed": dict(base["closed"]), "open": dict(base["open"])}
    merged["closed"].update(user.get("closed") or {})
    merged["open"].update(user.get("open") or {})
    return merged


async def run_preset(
    url: str,
    profile: str,
    timeout: float,
    config: Optional[Dict[str, Any]] = None,
    csv_path: Optional[str] = None,
):
    """
    Runs the preset: closed-loop sweep (calibration) + open-loop runs,
    and writes all median summaries to a single CSV file.
    """
    preset = _preset_from_config(profile, config)
    concurrency_list        = preset["closed"]["concurrencies"]
    total_per_concurrency   = preset["closed"]["total_per_c"]
    warmup_requests         = preset["closed"]["warmup"]
    repeat_runs             = preset["closed"]["repeat"]
    open_duration_sec       = preset["open"]["duration"]
    open_warmup_sec         = preset["open"]["warmup_sec"]

    # CSV destination (auto-named if not provided)
    if csv_path is None:
        csv_path = f"preset_{profile}_{int(time.time())}.csv"

    # Ensure we have a consistent timestamp for all rows
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    # Column schema (single file for both phases)
    fieldnames = [
        "phase",              # "closed_sweep" or "open_loop"
        "profile", "url", "timestamp",
        "concurrency",        # sweep: tested concurrency; open: concurrency_cap
        "total_requests",     # sweep only
        "open_duration_sec",  # open only
        "warmup",             # warmup requests (sweep) or seconds (open)
        "repeat",             # repeats used for medians
        "open_target_rps",  # open only
        "throughput_rps",     # sweep: median throughput; open: same as achieved_rps
        "p50_ms", "p90_ms", "p99_ms",
        "errors",             # average errors per run (from summaries)
    ]

    # 1) Closed-loop calibration via run_sweep
    results = await run_sweep(
        url=url,
        total=total_per_concurrency,
        concurrencies=concurrency_list,
        timeout=timeout,
        warmup=warmup_requests,
        repeat=repeat_runs,
        quiet=False,
    )

    # Open CSV and dump sweep rows
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for conc, summary in results:
            w.writerow({
                "phase": "closed_sweep",
                "profile": profile, "url": url, "timestamp": ts,
                "concurrency": conc,
                "total_requests": total_per_concurrency,
                "open_duration_sec": "",  # not applicable for sweep
                "warmup": warmup_requests,
                "repeat": repeat_runs,
                "open_target_rps": "",  # not applicable for sweep
                "throughput_rps": summary["throughput"],
                "p50_ms": summary["p50_ms"],
                "p90_ms": summary["p90_ms"],
                "p99_ms": summary["p99_ms"],
                "errors": summary["errors"],
            })

        # Pick best concurrency by median throughput
        best_concurrency, best_summary = max(results, key=lambda x: x[1]["throughput"])
        calibrated_rps = best_summary["throughput"]

        # 2) Open-loop targets around calibrated capacity
        open_targets_rps = [
            max(50.0, 0.5 * calibrated_rps),
            max(50.0, 0.9 * calibrated_rps),
            max(50.0, 1.1 * calibrated_rps),
        ]
        concurrency_cap = min(int(2.5 * best_concurrency), 2000)  # keep client safe by default

        print("\n=== preset: open-loop around calibrated capacity ===")
        print(f"Calibrated from closed-loop: T*={calibrated_rps:.1f} rps at C*={best_concurrency}")
        for target in open_targets_rps:
            print(f"\n--- open target ≈ {target:.0f} rps for {open_duration_sec:.0f}s (cap {concurrency_cap}) ---")
            open_summary = await run_open(
                url, target, open_duration_sec, concurrency_cap, timeout, open_warmup_sec, repeat_runs, quiet=False
            )

            # Write open-loop row
            w.writerow({
                "phase": "open_loop",
                "profile": profile, "url": url, "timestamp": ts,
                "concurrency": concurrency_cap,         # cap used
                "total_requests": "",                   # not applicable for open-loop
                "open_duration_sec": open_duration_sec,
                "warmup": open_warmup_sec,              # seconds
                "repeat": repeat_runs,
                "open_target_rps": target,
                "throughput_rps": open_summary["throughput"],
                "p50_ms": open_summary["p50_ms"],
                "p90_ms": open_summary["p90_ms"],
                "p99_ms": open_summary["p99_ms"],
                "errors": open_summary["errors"],
            })

    print(f"\nSaved preset CSV to {csv_path}")
    print(f"Best closed-loop: {calibrated_rps:.1f} rps at concurrency {best_concurrency}")
    print(f"Open-loop targets tested: {[int(x) for x in open_targets_rps]} rps with cap {concurrency_cap}")
    return csv_path
