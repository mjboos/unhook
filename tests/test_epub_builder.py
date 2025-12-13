"""Tests for EPUB creation utilities."""

from datetime import UTC, datetime

from ebooklib import ITEM_DOCUMENT, ITEM_IMAGE, epub

from unhook.epub_builder import EpubBuilder
from unhook.post_content import PostContent


def test_epub_builder_creates_chapter_and_image(tmp_path):
    post = PostContent(
        title="Sample Post",
        author="tester.bsky.social",
        published=datetime(2024, 1, 1, tzinfo=UTC),
        body="**Hello** world",
        image_urls=["https://example.com/image.jpg"],
    )

    builder = EpubBuilder(title="Test Export")
    output = tmp_path / "output.epub"
    builder.build([post], {"https://example.com/image.jpg": b"imgdata"}, output)

    book = epub.read_epub(output)
    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    images = list(book.get_items_of_type(ITEM_IMAGE))

    assert output.exists()
    assert len([doc for doc in documents if doc.file_name.startswith("post_")]) == 1
    assert len(images) == 1
    html_bodies = "\n".join(doc.get_content().decode() for doc in documents)
    assert "Hello" in html_bodies
    assert "tester.bsky.social" in html_bodies


def test_epub_builder_handles_empty_posts(tmp_path):
    builder = EpubBuilder(title="Test Export")
    output = tmp_path / "output.epub"

    builder.build([], {}, output)

    book = epub.read_epub(output)
    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    post_docs = [doc for doc in documents if doc.file_name.startswith("post_")]

    assert output.exists()
    assert len(post_docs) == 1
    assert b"No posts available" in post_docs[0].get_content()
