"""Command line entry points.

    walkout-load                     apply the schema
    walkout-simulate --clickhouse    generate telemetry and insert it
    walkout-simulate --out data/     generate telemetry to gzipped CSV
    walkout-doctor                   check credentials before a long run

Or via the Makefile, which is the shorter path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import clickhouse as ch
from . import simulation
from .config import ConfigError, clickhouse as clickhouse_config


def load(argv: list[str] | None = None) -> int:
    """Apply sql/schema.sql to the configured cluster."""
    try:
        client = ch.connect()
        ch.apply_schema(client)
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    print("schema applied: walkout.playback_events, walkout.titles")
    return 0


def simulate(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="walkout-simulate", description=simulation.__doc__)
    parser.add_argument("--sessions", type=int, default=250_000)
    parser.add_argument("--chunk", type=int, default=25_000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, help="write gzipped CSV chunks here")
    parser.add_argument("--clickhouse", action="store_true", help="insert directly")
    args = parser.parse_args(argv)

    if not args.out and not args.clickhouse:
        parser.error("pick --out DIR or --clickhouse")

    sinks = []
    if args.clickhouse:
        try:
            client = ch.connect()
        except ConfigError as exc:
            print(f"config: {exc}", file=sys.stderr)
            return 2
        client.command("TRUNCATE TABLE IF EXISTS walkout.playback_events")
        client.command("TRUNCATE TABLE IF EXISTS walkout.titles")
        ch.insert_columns(
            client,
            "walkout.titles",
            {k: [v] for k, v in simulation.TITLE.items()},
            list(simulation.TITLE),
        )
        sinks.append(
            lambda cols, _c=client: ch.insert_columns(
                _c, "walkout.playback_events", cols, simulation.COLUMNS
            )
        )
    if args.out:
        counter = {"part": 0}

        def to_csv(cols, out=args.out, counter=counter):
            simulation.write_csv_chunk(out, counter["part"], cols)
            counter["part"] += 1

        sinks.append(to_csv)

    def fan_out(cols):
        for sink in sinks:
            sink(cols)

    truth = simulation.generate(
        sessions=args.sessions, chunk=args.chunk, seed=args.seed, on_chunk=fan_out
    )
    print(f"\n{truth['events']:,} events across {truth['sessions']:,} sessions")
    print("ground truth -> data/ground_truth.json")
    return 0


def evaluate(argv: list[str] | None = None) -> int:
    """Grade the pipeline against the planted ground truth."""
    from .evaluation import evaluate as run, render

    try:
        client = ch.connect()
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    report = run(client)
    print(render(report))
    return 0 if report.passed else 1


def doctor(argv: list[str] | None = None) -> int:
    """Fail fast and loudly, before a twenty-minute load discovers the problem."""
    try:
        config = clickhouse_config()
    except ConfigError as exc:
        print(f"ClickHouse config: {exc}", file=sys.stderr)
        return 2
    print(f"ClickHouse   {config.username}@{config.host}:{config.port}")
    try:
        client = ch.connect(config)
        version = client.command("SELECT version()")
    except Exception as exc:  # noqa: BLE001 -- surface whatever the driver says
        print(f"  connection failed: {exc}", file=sys.stderr)
        return 1
    print(f"  connected, server {version}")

    tables = client.query("SELECT name FROM system.tables WHERE database = 'walkout'")
    names = [r[0] for r in tables.result_rows]
    print(f"  tables: {', '.join(names) if names else 'none yet (run make load)'}")
    if "playback_events" in names:
        count = client.command("SELECT count() FROM walkout.playback_events")
        print(f"  playback_events: {int(count):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(simulate(sys.argv[1:]))
