"""Parser child process: bounded records, CPU time and preview output size."""

import json
import resource
import sys
from pathlib import Path

from .config import settings
from .parsers import extract


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (settings.parser_timeout, settings.parser_timeout))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    print(json.dumps(["filename", sys.argv[2]]), flush=True)
    for reference, content in extract(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])):
        if len(content.encode()) > settings.max_record_bytes:
            raise ValueError("Individual record exceeds configured limit")
        print(json.dumps([reference, content]), flush=True)


if __name__ == "__main__":
    main()
