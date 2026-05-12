"""Tests for audio chunking functionality."""

import pytest
from jobs.chunking import (
    merge_chunk_results,
    CHUNK_DURATION_SECONDS,
    CHUNK_THRESHOLD_SECONDS,
    OVERLAP_SECONDS,
)


class TestChunkingConstants:
    """Test chunking configuration values."""

    def test_chunk_duration(self):
        """Chunk duration is 10 minutes."""
        assert CHUNK_DURATION_SECONDS == 10 * 60

    def test_chunk_threshold(self):
        """Chunking starts at 30 minutes."""
        assert CHUNK_THRESHOLD_SECONDS == 30 * 60

    def test_overlap(self):
        """Overlap is 30 seconds."""
        assert OVERLAP_SECONDS == 30


class TestMergeChunkResults:
    """Test chunk result merging."""

    def test_merge_single_chunk(self):
        """Single chunk returns its result."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "Hello world"}
        ]
        result = merge_chunk_results(chunks)
        assert result == "Hello world"

    def test_merge_multiple_chunks_in_order(self):
        """Multiple chunks are merged in order."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "First chunk text"},
            {"config": {"chunk_num": 1}, "result": "overlap words here Second chunk text"},
            {"config": {"chunk_num": 2}, "result": "more overlap words Third chunk text"},
        ]
        result = merge_chunk_results(chunks, overlap_words=3)
        # First chunk is kept as-is, others skip first 3 words
        assert "First chunk text" in result
        assert "Second chunk text" in result
        assert "Third chunk text" in result

    def test_merge_out_of_order_chunks(self):
        """Chunks are sorted by chunk_num before merging."""
        chunks = [
            {"config": {"chunk_num": 2}, "result": "Third"},
            {"config": {"chunk_num": 0}, "result": "First"},
            {"config": {"chunk_num": 1}, "result": "Second"},
        ]
        result = merge_chunk_results(chunks, overlap_words=0)
        parts = result.split()
        assert parts[0] == "First"
        assert "Second" in parts
        assert parts[-1] == "Third"

    def test_merge_with_empty_chunks(self):
        """Empty chunks are skipped."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "First"},
            {"config": {"chunk_num": 1}, "result": ""},
            {"config": {"chunk_num": 2}, "result": "Third"},
        ]
        result = merge_chunk_results(chunks, overlap_words=0)
        assert "First" in result
        assert "Third" in result

    def test_merge_with_missing_result(self):
        """Missing results are handled."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "First"},
            {"config": {"chunk_num": 1}},  # No result key
        ]
        result = merge_chunk_results(chunks, overlap_words=0)
        assert result == "First"

    def test_merge_overlap_removal(self):
        """Overlap words are removed from subsequent chunks."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "Hello world this is the first chunk"},
            {"config": {"chunk_num": 1}, "result": "the first chunk and here is more text"},
        ]
        result = merge_chunk_results(chunks, overlap_words=4)
        # Second chunk should skip first 4 words ("the first chunk and")
        assert "Hello world this is the first chunk" in result
        assert "here is more text" in result
        # Should not have duplicate "the first chunk"
        assert result.count("the first chunk") == 1

    def test_merge_no_overlap_removal(self):
        """Zero overlap keeps all words."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "First part"},
            {"config": {"chunk_num": 1}, "result": "Second part"},
        ]
        result = merge_chunk_results(chunks, overlap_words=0)
        assert result == "First part Second part"

    def test_merge_handles_short_chunks(self):
        """Short chunks with fewer words than overlap are handled."""
        chunks = [
            {"config": {"chunk_num": 0}, "result": "Long enough text here"},
            {"config": {"chunk_num": 1}, "result": "hi"},  # Only 1 word
        ]
        result = merge_chunk_results(chunks, overlap_words=30)
        # Short chunk should be kept as-is (not enough words to skip)
        assert "Long enough text here" in result
        assert "hi" in result
