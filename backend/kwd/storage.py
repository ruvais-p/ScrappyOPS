"""Private photo storage (visit photos, odometer photos, bills, installation photos). Files live in MEDIA_ROOT/kwd-photos/<user id>/...
A person can add files only under their own folder; managers and Head Office can read every photo; everyone else only their own.
A "signed" address is a link that works for a short time, like the one the old storage service gave."""
import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.core import signing

ROOT_NAME = "kwd-photos"
SALT = "kwd-photo-link"
# <user id>/<file>, or with up to two sub-folders (the visit screen files photos under <user id>/<date>/<file>)
NAME_RE = re.compile(r"^[0-9a-f\-]{36}(?:/[A-Za-z0-9_.\-]{1,120}){1,3}$")


def root():
    p = Path(settings.MEDIA_ROOT) / ROOT_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def valid_name(path):
    return bool(path) and bool(NAME_RE.match(path)) and ".." not in path


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
    f = file_of(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists():
        raise FileExistsError(path)
    f.write_bytes(data)


def sign(path, seconds=3600):
    return signing.dumps({"p": path}, salt=SALT)


def unsign(token, max_age):
    return signing.loads(token, salt=SALT, max_age=max_age)["p"]
