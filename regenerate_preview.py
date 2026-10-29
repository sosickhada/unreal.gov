"""Compatibility command; durable queue only, never direct API execution."""
import sys
from bureau.compat import enqueue

if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('Usage: python regenerate_preview.py CONTENT_ID')
    enqueue('render', int(sys.argv[1]))
