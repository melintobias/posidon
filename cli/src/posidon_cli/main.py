"""Define the Posidon command-line entry point."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 # Typer resolves annotations at runtime.
from typing import Annotated

from typer import Argument
from typer import BadParameter
from typer import Context
from typer import Option
from typer import Typer

from .logger import get_logger
from .options import CliOptions
from .options import DEFAULT_CLI_OPTIONS
from .options import OUTPUT_DIR_OPTION
from .options import OutputFormat
from .options import TAG_VERSION_OPTION
from .options import ThumbnailFormat
from .pipeline import IntakeStage
from .pipeline import MovingStage
from .pipeline import PipelineStage
from .pipeline.retrieval import RetrievalStage
from .pipeline.tagging import check_tag_version
from .pipeline.tagging import TaggingStage
from .pipeline.types import PipelineSharedStorage
from .pipeline.types import StageOrchestrator

app = Typer()
"""Typer application exposed by the `posidon` command."""

stages: list[type[PipelineStage]] = [
    IntakeStage,
    RetrievalStage,
    TaggingStage,
    MovingStage,
]
"""Ordered pipeline stages run by the command-line application."""


@app.command()
def main(  # noqa: PLR0913 # Typer maps each option to a parameter.
    ctx: Context,
    urls: Annotated[list[str] | None, Argument()] = None,  # noqa: ARG001
    *,
    debug: Annotated[
        bool, Option("--debug", "-d", help="Show diagnostic logging.")
    ] = DEFAULT_CLI_OPTIONS.debug,
    no_prompt: Annotated[  # noqa: ARG001
        bool,
        Option(
            "--no-prompt",
            help="Exit when no URLs are provided, instead of prompting for "
            "input.",
        ),
    ] = DEFAULT_CLI_OPTIONS.no_prompt,
    output_format: Annotated[  # noqa: ARG001
        OutputFormat, Option("--output-format", help="Output audio format.")
    ] = DEFAULT_CLI_OPTIONS.output_format,
    tag_version: Annotated[  # noqa: ARG001
        str | None,
        Option(
            TAG_VERSION_OPTION,
            help="Metadata tag version for the output format: id3v2.3 or "
            "id3v2.4 for mp3. Defaults to id3v2.4 for mp3.",
        ),
    ] = DEFAULT_CLI_OPTIONS.tag_version,
    thumbnail_format: Annotated[  # noqa: ARG001
        ThumbnailFormat,
        Option(
            "--thumbnail-format", help="Image format for embedded cover art."
        ),
    ] = DEFAULT_CLI_OPTIONS.thumbnail_format,
    output_dir: Annotated[  # noqa: ARG001
        Path | None,
        Option(
            OUTPUT_DIR_OPTION,
            "-o",
            file_okay=False,
            help="Directory for finished tracks. Defaults to the music "
            "directory, or the current directory if that doesn't exist.",
        ),
    ] = DEFAULT_CLI_OPTIONS.output_dir,
) -> None:
    """Process the supplied media URLs through the Posidon pipeline.

    Args:
        ctx: Typer command context.
        urls: Source URLs to process.
        debug: Whether to include diagnostic debug records.
        no_prompt: Whether to exit when no URLs are provided, instead of
            prompting for input.
        output_format: Audio format used for conversion and tagging.
        tag_version: Tag version for the output format's tag writer, or
            `None` to use the writer's default.
        thumbnail_format: Image format to use for the embedded cover artwork.
        output_dir: Directory receiving finished audio files, or `None` to
            use the platform's music directory.

    Raises:
        BadParameter: If the output format's tag writer does not support the
            requested tag version.
    """
    options = CliOptions.get_context_options(ctx)
    # Check after parsing every option, so the flags work in either order.
    try:
        check_tag_version(options.output_format, options.tag_version)
    except ValueError as error:
        raise BadParameter(
            str(error), ctx=ctx, param_hint=f"'{TAG_VERSION_OPTION}'"
        ) from error

    storage = PipelineSharedStorage(
        options=options, logger=get_logger(debug=debug)
    )
    orchestrator = StageOrchestrator(stages, storage)
    orchestrator.run()


if __name__ == "__main__":
    app()
