"""EPUB builder utilities."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

import bleach
import markdown2
from ebooklib import epub

from unhook.post_content import PostContent

logger = logging.getLogger(__name__)

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "p",
    "img",
    "h1",
    "h2",
    "h3",
    "pre",
    "code",
]
ALLOWED_ATTRIBUTES = {"img": ["src", "alt"], "a": ["href", "title", "rel"]}


def _sanitize_content(text: str) -> str:
    """Convert markdown to HTML and sanitize."""

    rendered = markdown2.markdown(text or "")
    return bleach.clean(rendered, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def _guess_media_type(url: str) -> str:
    media_type, _ = mimetypes.guess_type(url)
    return media_type or "image/jpeg"


class EpubBuilder:
    """Create EPUB files from posts."""

    def __init__(self, title: str = "Feed Export", language: str = "en") -> None:
        self.title = title
        self.language = language

    def build(
        self,
        posts: list[PostContent],
        image_bytes: dict[str, bytes],
        output_path: Path,
    ) -> Path:
        """Build an EPUB file from post content."""

        book = epub.EpubBook()
        book.set_identifier("unhook-export")
        book.set_title(self.title)
        book.set_language(self.language)

        content_sections: list[str] = []
        for idx, post in enumerate(posts, start=1):
            body_html = _sanitize_content(post.body)
            image_tags: list[str] = []
            for image_idx, image_url in enumerate(post.image_urls, start=1):
                content = image_bytes.get(image_url)
                if not content:
                    logger.warning("Missing bytes for image %s", image_url)
                    continue

                image_name = f"images/post_{idx}_{image_idx}"
                media_type = _guess_media_type(image_url)
                extension = mimetypes.guess_extension(media_type) or ".img"
                file_name = f"{image_name}{extension}"

                image_item = epub.EpubItem(
                    uid=file_name,
                    file_name=file_name,
                    media_type=media_type,
                    content=content,
                )
                book.add_item(image_item)
                image_tags.append(
                    f'<p><img src="{file_name}" alt="Image {image_idx}" /></p>'
                )

            author = bleach.clean(post.author)
            published = post.published.isoformat()
            metadata_html = f"<p><em>{author} - {published}</em></p>"
            content_sections.append(f"{metadata_html}{body_html}{''.join(image_tags)}")
            if idx < len(posts):
                content_sections.append("<hr />")

        chapter = epub.EpubHtml(
            title=self.title, file_name="post_1.xhtml", lang=self.language
        )
        chapter.content = "".join(content_sections)

        book.add_item(chapter)
        book.spine = ["nav", chapter]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.toc = [chapter]

        epub.write_epub(str(output_path), book)
        return output_path


__all__ = ["EpubBuilder"]
