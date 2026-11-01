"""Keep the gateway fallback workspace identical to the current developer page."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sync(check=False):
    target = ROOT / 'static/shared/developer-mode.js'
    source = target.read_text()
    literal = json.dumps((ROOT / 'static/dev.html').read_text(), ensure_ascii=False)
    updated, count = re.subn(r'^  const FALLBACK_WORKSPACE = .*;$', lambda _: '  const FALLBACK_WORKSPACE = ' + literal + ';', source, flags=re.M)
    if count != 1: raise ValueError('Fallback marker not found')
    if check and updated != source: raise ValueError('Developer fallback is stale; run python scripts/sync_developer_fallback.py')
    if not check: target.write_text(updated)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true')
    sync(parser.parse_args().check)
