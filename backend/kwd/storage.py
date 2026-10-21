"""Private photo storage (visit photos, odometer photos, bills, installation photos). Files live in MEDIA_ROOT/kwd-photos/<user id>/...
A person can add files only under their own folder; managers and Head Office can read every photo; everyone else only their own.
A "signed" address is a link that works for a short time, like the one the old storage service gave."""
import hashlib
import io
import re
from pathlib import Path

from django.conf import settings
from django.core import signing

ROOT_NAME = "kwd-photos"
SALT = "kwd-photo-link"
# <user id>/<file>, or with up to two sub-folders (the visit screen files photos under <user id>/<date>/<file>)
NAME_RE = re.compile(r"^[0-9a-f\-]{36}(?:/[A-Za-z0-9_.\-]{1,120}){1,3}$")
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 24_000_000


def root():
    p = Path(settings.MEDIA_ROOT) / ROOT_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def valid_name(path):
    return bool(path) and bool(NAME_RE.fullmatch(path)) and ".." not in path and path.lower().endswith(".jpg")


def file_of(path):
    return root() / path


def exists(path):
    return valid_name(path) and file_of(path).is_file()


def etag(path):
    """Same file content -> same value. Used to catch the same bill photo being used twice."""
    if not exists(path):
        return None
    return hashlib.md5(file_of(path).read_bytes()).hexdigest()


def save(path, data):
    # Decode then re-encode: never persist attacker-controlled active formats, metadata, or MIME types.
    from PIL import Image, UnidentifiedImageError
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photo is empty or too large")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP") or image.width * image.height > MAX_PHOTO_PIXELS:
                raise ValueError("Unsupported or oversized image")
            image.load()
            rgb = image.convert("RGB")
            output = io.BytesIO()
            rgb.save(output, format="JPEG", quality=88, optimize=True)
            data = output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError("Invalid image") from exc
    f = file_of(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists():
        raise FileExistsError(path)
    f.write_bytes(data)


def sign(path, seconds=3600):
    import time
    return signing.dumps({"p": path, "exp": int(time.time()) + seconds}, salt=SALT)


def unsign(token, max_age):
    import time
    from django.core.signing import BadSignature
    data = signing.loads(token, salt=SALT, max_age=86400 * 7)
    # Old links had no embedded expiration; cap their lifetime at seven days from signing.
    if "exp" in data and int(data["exp"]) < int(time.time()):
        raise BadSignature("Expired photo URL")
    if "p" not in data:
        raise BadSignature("Invalid photo URL")
    return data["p"]
