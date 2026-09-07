"""Entry point.

All diagnostics go to stderr. On the stdio transport a single stray byte on
stdout corrupts the JSON-RPC framing, which is the first failure mode anyone
hits when writing an MCP server.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bestrom-mcp",
        description="MCP server for the BestROM Android 17 tree (POCO F6, peridot)",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (default, what MCP clients spawn) or http for streamable HTTP",
    )
    parser.add_argument("--config", default=None, help="path to a TOML config file")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--version", action="version", version=f"bestrom-mcp {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("bestrom_mcp")

    try:
        cfg = load_config(args.config, require_tree=True)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2

    from .server import build_server

    server = build_server(cfg)
    log.info("bestrom-mcp %s serving tree %s over %s", __version__, cfg.tree.root, args.transport)
    server.run(transport="stdio" if args.transport == "stdio" else "streamable-http")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
