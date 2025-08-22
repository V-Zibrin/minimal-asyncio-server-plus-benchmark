import argparse
import asyncio
import json
from typing import Optional, Dict, Any

from bench_core import run_closed, run_open, run_sweep, run_preset


def load_config(config_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not config_path:
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="optional JSON config (presets only)", default="bench_config.json")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # TODO: primarily keep all of these in the config?

    closed_cmd = subparsers.add_parser("closed", help="fixed N requests with concurrency C")
    closed_cmd.add_argument("--url", default="http://127.0.0.1:8000/")
    closed_cmd.add_argument("-n", "--total", type=int, default=1000)
    closed_cmd.add_argument("-c", "--concurrency", type=int, default=100)
    closed_cmd.add_argument("--timeout", type=float, default=5.0)
    closed_cmd.add_argument("--warmup", type=int, default=0)
    closed_cmd.add_argument("--repeat", type=int, default=1)
    closed_cmd.add_argument("--quiet", action="store_true")

    open_cmd = subparsers.add_parser("open", help="open-loop: target RPS for D seconds")
    open_cmd.add_argument("--url", default="http://127.0.0.1:8000/")
    open_cmd.add_argument("--rps", type=float, default=1000.0)
    open_cmd.add_argument("--duration", type=float, default=10.0)
    open_cmd.add_argument("--concurrency", type=int, default=500)
    open_cmd.add_argument("--timeout", type=float, default=5.0)
    open_cmd.add_argument("--warmup-sec", type=float, default=0.0)
    open_cmd.add_argument("--repeat", type=int, default=1)
    open_cmd.add_argument("--quiet", action="store_true")

    sweep_cmd = subparsers.add_parser("sweep", help="closed-loop across concurrencies (medians)")
    sweep_cmd.add_argument("--url", default="http://127.0.0.1:8000/")
    sweep_cmd.add_argument("-n", "--total", type=int, default=1000)
    sweep_cmd.add_argument("--concurrencies", default="1,2,5,10,20,50,100,200")
    sweep_cmd.add_argument("--timeout", type=float, default=5.0)
    sweep_cmd.add_argument("--warmup", type=int, default=0)
    sweep_cmd.add_argument("--repeat", type=int, default=1)

    preset_cmd = subparsers.add_parser("preset", help="calibrate (closed) + open-loop suite (configurable)")
    preset_cmd.add_argument("--url", default="http://127.0.0.1:8000/")
    preset_cmd.add_argument("--profile", choices=["smoke", "standard", "stress"], default="standard")
    preset_cmd.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args()
    config = load_config(args.config)

    if args.mode == "closed":
        asyncio.run(
            run_closed(args.url, args.total, args.concurrency, args.timeout, args.warmup, args.repeat, args.quiet))
    elif args.mode == "open":
        asyncio.run(
            run_open(args.url, args.rps, args.duration, args.concurrency, args.timeout, args.warmup_sec, args.repeat,
                     args.quiet))
    elif args.mode == "sweep":
        concurrency_list = [int(x) for x in args.concurrencies.split(",")]
        asyncio.run(run_sweep(args.url, args.total, concurrency_list, args.timeout, args.warmup, args.repeat))
    else:
        asyncio.run(run_preset(args.url, args.profile, args.timeout, config))


if __name__ == "__main__":
    main()
