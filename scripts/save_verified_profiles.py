from __future__ import annotations

import json
from pathlib import Path

from backend import reliability
from scripts.live_readonly_benchmark import configuration


def main():
    owner, provider, _, _ = configuration()
    saved = []
    for name in ('live-json-protocol.json', 'live-gpt-planner.json', 'live-final-validated.json', 'live-engine-final.json'):
        path = Path('docs') / name
        if not path.is_file():
            continue
        for row in json.loads(path.read_text()).get('results', []):
            success = row.get('success') or row.get('status') == 'completed'
            if success and row['model'] not in saved:
                reliability.remember_protocol(owner, provider['id'], row['model'], 'json')
                saved.append(row['model'])
    print(json.dumps({'verified_protocol_profiles': saved}, ensure_ascii=False))


if __name__ == '__main__':
    main()
