"""Private staged writes: an interrupted export must not truncate a good file."""
import json
import os
import tempfile
from pathlib import Path


def distinct_output(output, *inputs):
    destination = os.path.normcase(os.path.realpath(output))
    for source in inputs:
        if not source:
            continue
        if destination == os.path.normcase(os.path.realpath(source)):
            raise ValueError("Output must not replace an input file")
        if os.path.exists(output) and os.path.exists(source) and os.path.samefile(output, source):
            raise ValueError("Output must not replace an input file")


def atomic_write(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".maskbridge-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, payload):
    atomic_write(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
