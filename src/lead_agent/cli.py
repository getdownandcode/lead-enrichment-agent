"""Typer command line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import Settings
from .orchestrator import EnrichmentOrchestrator
from .utils import normalize_domain
from .writers import write_csv, write_json

app = typer.Typer(add_completion=False, help="Autonomous, evidence-first lead enrichment.")
console = Console()


@app.callback()
def main() -> None:
    """Company lead-enrichment commands."""


@app.command()
def run(
    domains: list[str] = typer.Option(..., "--domains", "-d", help="One or more company domains."),
    output: Path = typer.Option(Path("output/output.json"), help="JSON output path."),
    csv: Path | None = typer.Option(Path("output/output.csv"), help="CSV output path."),
    write_csv_file: bool = typer.Option(
        True, "--write-csv/--no-csv", help="Write or skip the CSV artifact."
    ),
    max_pages: int | None = typer.Option(
        None, min=1, max=20, help="Maximum relevant pages per domain."
    ),
    search_enabled: bool = typer.Option(
        True, "--search-enabled/--no-search", help="Use Tavily when leadership is absent."
    ),
) -> None:
    """Enrich domains using public web evidence, Gemini, and optionally Tavily."""
    settings = Settings()
    if max_pages:
        settings.max_pages = max_pages
    valid: list[str] = []
    for raw in domains:
        try:
            value = normalize_domain(raw)
            if value not in valid:
                valid.append(value)
        except ValueError as exc:
            console.print(f"[yellow]Skipping {raw!r}: {exc}[/yellow]")
    if not valid:
        raise typer.Exit(2)
    agent = EnrichmentOrchestrator(settings, use_search=search_enabled)

    async def execute():
        results = []
        try:
            with Progress(
                SpinnerColumn(), TextColumn("{task.description}"), console=console
            ) as progress:
                task = progress.add_task("Enriching domains", total=len(valid))
                for domain in valid:
                    progress.update(task, description=f"Enriching {domain}")
                    results.append(await agent.enrich(domain))
                    progress.advance(task)
            return results
        finally:
            await agent.close()

    results = asyncio.run(execute())
    write_json(results, output)
    if csv and write_csv_file:
        write_csv(results, csv)
    table = Table(title="Enrichment complete")
    table.add_column("Domain")
    table.add_column("Status")
    table.add_column("Confidence")
    table.add_column("Pages")
    for result in results:
        table.add_row(
            result.domain,
            result.status,
            str(result.data_confidence_score),
            str(len(result.source_pages)),
        )
    console.print(table)
    console.print(
        f"[green]JSON:[/green] {output}"
        + (f"\n[green]CSV:[/green] {csv}" if csv and write_csv_file else "")
    )


if __name__ == "__main__":
    app()
