"""Command line entry points.

    walkout-load                     apply the schema
    walkout-simulate --clickhouse    generate telemetry and insert it
    walkout-simulate --out data/     generate telemetry to gzipped CSV
    walkout-eval                     grade the pipeline against ground truth
    walkout-agent sintel             run the agent over a title
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
    """Apply sql/schema.sql to the configured cluster.

    Safe to run repeatedly and safe to run on a deploy: every statement in the
    schema is CREATE ... IF NOT EXISTS, so existing data survives. Rebuilding
    the tables is `--reset`, which drops them and says how many rows that costs
    before it does.
    """
    parser = argparse.ArgumentParser(prog="walkout-load")
    parser.add_argument(
        "--reset", action="store_true",
        help="drop the tables first -- destroys all loaded telemetry",
    )
    args = parser.parse_args(argv)

    try:
        client = ch.connect()
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    if args.reset:
        for table in ch.list_tables(client):
            rows = int(client.command(f"SELECT count() FROM {table}"))
            print(f"dropping {table} ({rows:,} rows)")
            client.command(f"DROP TABLE IF EXISTS {table}")

    ch.apply_schema(client)
    print(f"schema applied: {', '.join(ch.list_tables(client))}")
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
        for table in ("playback_events", "sessions", "titles"):
            client.command(f"TRUNCATE TABLE IF EXISTS walkout.{table}")
        ch.insert_columns(
            client,
            "walkout.titles",
            {k: [v] for k, v in simulation.TITLE.items()},
            list(simulation.TITLE),
        )
        sinks.append(
            lambda cols, _c=client: ch.insert_columns(
                _c, "walkout.sessions", cols, simulation.SESSION_COLUMNS
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

    if args.clickhouse:
        degraded = next(c for c in simulation.CLIFFS if c["cause"] == "technical")
        print("\nexpanding sessions into events inside ClickHouse...", flush=True)
        rows = ch.expand_events(
            client,
            title_id=simulation.TITLE["title_id"],
            bucket_sec=simulation.BUCKET_SEC,
            degraded_start=degraded["start"],
            degraded_end=degraded["end"],
        )
        print(f"{rows:,} events across {truth['sessions']:,} sessions")
    else:
        print(f"\n{truth['events']:,} events across {truth['sessions']:,} sessions")

    print("ground truth -> data/ground_truth.json")
    return 0


def evaluate(argv: list[str] | None = None) -> int:
    """Grade the pipeline against the planted ground truth.

    `--mcp` grades over the same path the agent uses, through the official
    ClickHouse MCP server, so "it works in the agent" is a measured claim
    rather than a hopeful one.
    """
    from .evaluation import evaluate as run, render

    parser = argparse.ArgumentParser(prog="walkout-eval")
    parser.add_argument(
        "--mcp", action="store_true",
        help="read through the ClickHouse MCP server instead of the driver",
    )
    args = parser.parse_args(argv)

    try:
        if args.mcp:
            from .mcp_warehouse import McpWarehouse

            warehouse = McpWarehouse()
        else:
            warehouse = ch.DirectWarehouse()
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    print(f"reading via: {'clickhouse mcp server' if args.mcp else 'clickhouse driver'}")
    report = run(warehouse)
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


def agent(argv: list[str] | None = None) -> int:
    """Run the agent over one title and print its investigation as it happens.

    The tool calls are printed as they are made, because the point of the
    product is the reasoning, not just the verdict: you can watch it find the
    cliffs, slice them, and go and look at the film.
    """
    import asyncio

    parser = argparse.ArgumentParser(prog="walkout-agent")
    parser.add_argument("title_id", nargs="?", default="sintel")
    parser.add_argument("--ask", default=None, help="ask something else entirely")
    parser.add_argument("--quiet", action="store_true", help="verdict only")
    args = parser.parse_args(argv)

    prompt = args.ask or (
        f"Analyse {args.title_id}. Work through every cliff and tell me what to fix."
    )
    try:
        return asyncio.run(_run_agent(prompt, quiet=args.quiet))
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


async def _run_agent(prompt: str, quiet: bool = False) -> int:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from .agent import root_agent

    runner = InMemoryRunner(agent=root_agent, app_name="walkout")
    session = await runner.session_service.create_session(
        app_name="walkout", user_id="cli"
    )
    async for event in runner.run_async(
        user_id="cli",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        for part in event.content.parts if event.content else []:
            if part.function_call and not quiet:
                print(f"  -> {part.function_call.name}", file=sys.stderr, flush=True)
            elif part.text and event.author != "user":
                print(part.text, end="", flush=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(simulate(sys.argv[1:]))
