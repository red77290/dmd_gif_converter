"""
Top-level package alias for `dmd_gif_converter`.

Re-exports the headless library API from `src.engine.api` while preserving
full backward compatibility with `src.engine.*` and `src.plugins.*` imports.
"""

from src.engine.api import (
    DMDS_HEADER_FORMAT,
    DMDS_HEADER_SIZE,
    DMDS_MAGIC,
    DMDS_VERSION,
    STATIC_IMAGE_EXTENSIONS,
    SUPPORTS_DIRECT_RGB565_STREAM,
    DmdClipConfig,
    DmdMediaProcessor,
    DmdProcessedAssets,
    __version__,
    extract_frames_from_gif,
    is_static_image_source,
    read_rgb565_stream_header,
    resolve_panorama_scroll_axis,
    rgb565_le_to_rgb888,
    rgb888_to_rgb565_le,
    truncate_gif_bytes,
    truncate_rgb565_stream,
    write_rgb565_stream,
)

__all__ = [
    "__version__",
    "SUPPORTS_DIRECT_RGB565_STREAM",
    "STATIC_IMAGE_EXTENSIONS",
    "DMDS_MAGIC",
    "DMDS_VERSION",
    "DMDS_HEADER_FORMAT",
    "DMDS_HEADER_SIZE",
    "DmdClipConfig",
    "DmdProcessedAssets",
    "DmdMediaProcessor",
    "is_static_image_source",
    "rgb888_to_rgb565_le",
    "rgb565_le_to_rgb888",
    "write_rgb565_stream",
    "read_rgb565_stream_header",
    "resolve_panorama_scroll_axis",
    "truncate_rgb565_stream",
    "truncate_gif_bytes",
    "extract_frames_from_gif",
]
