"""Tests for EPUB creation utilities."""

from datetime import UTC, datetime

from ebooklib import ITEM_DOCUMENT, ITEM_IMAGE, epub

from unhook.epub_builder import EpubBuilder, _escape_hashtags
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


def test_escape_hashtags_at_line_start():
    """Hashtags at line start should be escaped to prevent heading conversion."""
    # Hashtag at start of text
    assert _escape_hashtags("#python is great") == r"\#python is great"

    # Hashtag in the middle of a line (should not be changed)
    assert _escape_hashtags("Hello #python") == "Hello #python"

    # Hashtag at start of a new line
    assert _escape_hashtags("Hello\n#bluesky rocks") == "Hello\n\\#bluesky rocks"

    # Multiple hashes (like ##trending)
    assert _escape_hashtags("##double") == r"\##double"

    # Hashtag with number
    assert _escape_hashtags("#123") == r"\#123"

    # Empty and None handling
    assert _escape_hashtags("") == ""
    assert _escape_hashtags(None) is None

    # Normal markdown heading (with space) should NOT be changed
    # because it's intentional markdown, not a hashtag
    assert _escape_hashtags("# Heading") == "# Heading"


def test_epub_builder_escapes_hashtags(tmp_path):
    """Hashtags in post body should not become headings in EPUB."""
    post = PostContent(
        title="Hashtag Post",
        author="tester.bsky.social",
        published=datetime(2024, 1, 1, tzinfo=UTC),
        body="#BlueskyDev is awesome\nCheck out #python",
        image_urls=[],
    )

    builder = EpubBuilder(title="Test Export")
    output = tmp_path / "output.epub"
    builder.build([post], {}, output)

    book = epub.read_epub(output)
    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    html_content = "\n".join(doc.get_content().decode() for doc in documents)

    # Hashtags should NOT be converted to headings
    assert (
        "<h1>" not in html_content
        or "BlueskyDev" not in html_content.split("<h1>")[1].split("</h1>")[0]
        if "<h1>" in html_content
        else True
    )
    # The hashtag text should still appear in the content
    assert "BlueskyDev" in html_content
    assert "python" in html_content
