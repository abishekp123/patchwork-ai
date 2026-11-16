import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from patchwork.errors import PatchworkError

SHA_PATTERN = r"[0-9a-fA-F]{40}"


def normalize_url(value: str) -> str:
    error = PatchworkError("invalid_url", "Use an HTTPS github.com/owner/repository URL.")
    if not value.isascii() or any(c.isspace() for c in value) or "%" in value or "\\" in value:
        raise error
    try:
        url = urlsplit(value)
    except ValueError:
        raise error from None
    if url.scheme != "https" or url.netloc.lower() != "github.com" or url.query or url.fragment:
        raise error
    parts = url.path.removesuffix("/").split("/")
    if len(parts) != 3 or parts[0]:
        raise error
    owner, name = parts[1].lower(), parts[2].lower()
    name = name.removesuffix(".git")
    if (
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?", owner)
        or "--" in owner
        or not re.fullmatch(r"[a-z0-9_.-]{1,100}", name)
        or name in {".", ".."}
    ):
        raise error
    return f"https://github.com/{owner}/{name}"


def validate_sha(value: str) -> str:
    if not re.fullmatch(SHA_PATTERN, value):
        raise PatchworkError("invalid_revision", "Commit must be a full 40-character SHA-1.")
    return value.lower()


def validate_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or len(value.encode("utf-8")) > 4096
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(char in value for char in ("\\", "\x00", ":"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise PatchworkError("unsafe_path", "Repository contains an unsafe source path.")
    return PurePosixPath(value).as_posix()
