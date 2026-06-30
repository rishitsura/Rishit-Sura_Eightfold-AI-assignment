"""
CLI entrypoint for the candidate data transformer.

Usage:
    python -m transformer.cli --input file1.csv file2.json resume.pdf \\
                              --config custom_config.json \\
                              --output result.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from transformer.pipeline import Pipeline


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.command(
    help="Multi-Source Candidate Data Transformer\n\n"
    "Transform candidate data from multiple sources (CSV, JSON, GitHub, "
    "resumes, recruiter notes) into a single canonical profile."
)
@click.option(
    "--input", "-i",
    "input_paths",
    multiple=True,
    required=True,
    help="Input file path(s) or URL(s). Can be specified multiple times.",
)
@click.option(
    "--config", "-c",
    "config_path",
    default=None,
    type=click.Path(exists=False),
    help="Path to output config JSON file. If not provided, uses the default schema.",
)
@click.option(
    "--output", "-o",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output file path. If not provided, prints to stdout.",
)
@click.option(
    "--github-token",
    default=None,
    envvar="GITHUB_TOKEN",
    help="GitHub personal access token (or set GITHUB_TOKEN env var).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose/debug logging.",
)
@click.option(
    "--pretty",
    is_flag=True,
    default=True,
    help="Pretty-print JSON output (default: true).",
)
@click.option(
    "--source-type", "-t",
    "source_type_overrides",
    multiple=True,
    type=(str, str),
    help="Override source type for a file: --source-type file.txt recruiter_notes",
)
def main(
    input_paths: tuple[str, ...],
    config_path: str | None,
    output_path: str | None,
    github_token: str | None,
    verbose: bool,
    pretty: bool,
    source_type_overrides: tuple[tuple[str, str], ...],
) -> None:
    """Run the candidate data transformation pipeline."""
    _setup_logging(verbose)
    logger = logging.getLogger("transformer.cli")

    # Validate inputs
    missing = []
    for path in input_paths:
        if not path.startswith("http") and not Path(path).exists():
            missing.append(path)

    if missing:
        click.echo(f"Error: Input file(s) not found: {', '.join(missing)}", err=True)
        sys.exit(1)

    # Validate config if provided
    if config_path and not Path(config_path).exists():
        click.echo(f"Error: Config file not found: {config_path}", err=True)
        sys.exit(1)

    # Build source type overrides dict
    overrides = {path: st for path, st in source_type_overrides}

    # Run pipeline
    logger.info("Starting pipeline with %d input(s)", len(input_paths))
    pipeline = Pipeline(github_token=github_token)

    try:
        results = pipeline.run_and_serialize(
            input_paths=list(input_paths),
            config_path=config_path,
            source_types=overrides,
        )
    except Exception as e:
        click.echo(f"Pipeline error: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if not results:
        click.echo("No candidates found in the provided inputs.", err=True)
        sys.exit(0)

    # Format output
    indent = 2 if pretty else None
    output_json = json.dumps(results, indent=indent, ensure_ascii=False, default=str)

    # Write or print
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        click.echo(f"Output written to {output_path}")
    else:
        click.echo(output_json)

    # Print validation summary
    for i, result in enumerate(results):
        validation = result.get("validation", {})
        is_valid = validation.get("valid", True)
        error_count = len(validation.get("errors", []))
        warning_count = len(validation.get("warnings", []))

        status = "✓ VALID" if is_valid else "✗ INVALID"
        profile = result.get("profile", {})
        name = profile.get("full_name", f"Candidate {i+1}")
        confidence = profile.get("overall_confidence", "N/A")

        logger.info(
            "%s | %s | confidence=%.2f | errors=%d warnings=%d",
            name, status,
            confidence if isinstance(confidence, (int, float)) else 0,
            error_count, warning_count,
        )


if __name__ == "__main__":
    main()
