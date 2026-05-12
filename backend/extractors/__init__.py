from .audio import AudioExtractor
from .video import VideoExtractor
from .youtube import YouTubeExtractor
from .pdf import PDFExtractor
from .webpage import WebpageExtractor
from .image import ImageExtractor
from .base import Extractor

_EXTRACTORS: dict[str, type[Extractor]] = {
    "audio": AudioExtractor,
    "video": VideoExtractor,
    "youtube": YouTubeExtractor,
    "pdf": PDFExtractor,
    "url": WebpageExtractor,
    "webpage": WebpageExtractor,
    "image": ImageExtractor,
}


def get_extractor(source_type: str) -> Extractor | None:
    """Get an extractor instance for the given source type."""
    extractor_cls = _EXTRACTORS.get(source_type)
    if extractor_cls is None:
        return None
    return extractor_cls()


__all__ = [
    "AudioExtractor",
    "VideoExtractor",
    "YouTubeExtractor",
    "PDFExtractor",
    "WebpageExtractor",
    "ImageExtractor",
    "get_extractor",
]
