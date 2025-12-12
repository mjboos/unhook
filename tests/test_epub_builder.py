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
    documents = book.get_items_of_type(ITEM_DOCUMENT)
    images = book.get_items_of_type(ITEM_IMAGE)

    assert output.exists()
    assert len(list(documents)) == 1
    assert len(list(images)) == 1
    html_content = next(book.get_items_of_type(ITEM_DOCUMENT)).get_content().decode()
    assert "Sample Post" in html_content
    assert "Hello" in html_content
