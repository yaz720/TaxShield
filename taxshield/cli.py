"""Command-line interface for TaxShield."""

import click

from .redactor import run_redaction


@click.group()
@click.version_option(version="0.1.0", prog_name="TaxShield")
def main():
    """TaxShield - Tax document PII redaction tool."""
    pass


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--output", "-o", default=None, help="Output directory (default: <input>/redacted/)")
@click.option("--preview", "-p", is_flag=True, default=False, help="Preview detected PII without redacting")
def redact(paths, output, preview):
    """Redact PII from tax documents.

    PATHS can be one or more files, or a directory.
    Supported formats: PDF, JPG, PNG.
    """
    if preview:
        click.echo("Preview mode: detecting PII without redacting...\n")
    else:
        click.echo("Redacting PII from tax documents...\n")

    try:
        result = run_redaction(list(paths), output, preview)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if result["files_processed"] == 0:
        click.echo("No supported files found.")
        return

    # Print results
    click.echo(f"Files processed: {result['files_processed']}")
    click.echo(f"PII items found: {result['total_pii_found']}")

    if result.get("file_results"):
        click.echo()
        for fr in result["file_results"]:
            click.echo(f"  {fr['file']}: {fr['pii_count']} PII items")
            if preview and fr["pii_items"]:
                for item in fr["pii_items"]:
                    click.echo(
                        f"    [{item.pii_type}] "
                        f"'{item.original_text}' -> '{item.replacement}' "
                        f"(confidence: {item.confidence})"
                    )

    if not preview:
        click.echo(f"\nRedacted files saved to: {result['output_dir']}")
        if result["mappings"]:
            click.echo(f"Mapping tables: redaction_map.txt, redaction_map.csv")
            click.echo("\nToken mappings:")
            for m in result["mappings"]:
                note = f"  ({m['note']})" if m["note"] else ""
                click.echo(f"  {m['token']} -> {m['original']}{note}")
    else:
        click.echo("\nPreview complete. No files were modified.")
        click.echo("Run without -p to apply redactions.")


if __name__ == "__main__":
    main()
