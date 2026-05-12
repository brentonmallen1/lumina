"""Tests for extraction cache utilities."""

import pytest
from jobs.cache import (
    compute_content_hash,
    extract_youtube_video_id,
    normalize_url,
    process_thumbnail,
)


class TestYouTubeVideoId:
    """Test YouTube video ID extraction."""

    def test_watch_url(self):
        """Extract from youtube.com/watch?v="""
        assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        """Extract from youtu.be/"""
        assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        """Extract from youtube.com/embed/"""
        assert extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_with_extra_params(self):
        """Extract ignoring extra query params."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLtest"
        assert extract_youtube_video_id(url) == "dQw4w9WgXcQ"

    def test_just_video_id(self):
        """Extract from bare video ID."""
        assert extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        """Return None for non-YouTube URL."""
        assert extract_youtube_video_id("https://example.com/video") is None

    def test_invalid_video_id(self):
        """Return None for invalid video ID."""
        assert extract_youtube_video_id("https://youtube.com/watch") is None


class TestNormalizeUrl:
    """Test URL normalization."""

    def test_lowercase(self):
        """URLs are lowercased."""
        result = normalize_url("HTTPS://EXAMPLE.COM/Path")
        assert result == "https://example.com/path"

    def test_removes_tracking_params(self):
        """Tracking parameters are removed."""
        url = "https://example.com/page?foo=bar&utm_source=twitter&utm_medium=social"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "foo=bar" in result

    def test_removes_trailing_slash(self):
        """Trailing slashes are removed."""
        result = normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_sorts_query_params(self):
        """Query params are sorted for consistent hashing."""
        url1 = normalize_url("https://example.com?b=2&a=1")
        url2 = normalize_url("https://example.com?a=1&b=2")
        assert url1 == url2

    def test_preserves_path(self):
        """Path is preserved."""
        result = normalize_url("https://example.com/foo/bar/baz")
        assert "/foo/bar/baz" in result


class TestContentHash:
    """Test content hash computation."""

    def test_youtube_hash(self):
        """YouTube URLs hash by video ID."""
        url1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        url2 = "https://youtu.be/dQw4w9WgXcQ"

        hash1 = compute_content_hash("youtube", url1)
        hash2 = compute_content_hash("youtube", url2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256

    def test_url_hash_normalized(self):
        """URL hashes use normalized URLs."""
        url1 = "https://EXAMPLE.COM/page?utm_source=test"
        url2 = "https://example.com/page"

        hash1 = compute_content_hash("url", url1)
        hash2 = compute_content_hash("url", url2)

        assert hash1 == hash2

    def test_text_hash(self):
        """Text content hashes consistently."""
        text = "Hello, world!"
        hash1 = compute_content_hash("text", text)
        hash2 = compute_content_hash("text", text)

        assert hash1 == hash2
        assert len(hash1) == 64

    def test_different_content_different_hash(self):
        """Different content produces different hashes."""
        hash1 = compute_content_hash("text", "Hello")
        hash2 = compute_content_hash("text", "World")

        assert hash1 != hash2


class TestProcessThumbnail:
    """Test thumbnail processing."""

    def test_process_valid_image(self):
        """Process a valid image."""
        # Create a simple 1x1 PNG
        import base64
        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        result = process_thumbnail(png_1x1)

        # Should return base64 string
        assert isinstance(result, str)
        if result:  # Only if Pillow is available
            # Should be valid base64
            decoded = base64.b64decode(result)
            assert len(decoded) > 0

    def test_process_invalid_image(self):
        """Invalid image returns empty string."""
        result = process_thumbnail(b"not an image")
        assert result == ""

    def test_empty_data(self):
        """Empty data returns empty string."""
        result = process_thumbnail(b"")
        assert result == ""
