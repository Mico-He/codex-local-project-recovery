"""Restore the same local project catalog to existing Codex account profiles.

This is an offline recovery tool, not an account-isolation preference.
It never changes authentication, cloud projects, permission roots, or chats.
"""
import argparse
import copy
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ACCOUNT_KEY = 'electron-account-renderer-state-v1'
ALLOWED = {'local-projects', 'project-order',
           'app-server-project-id-by-legacy-project-id-by-host'}


def profiles(state):
    yield 'current', state
    account = state.get(ACCOUNT_KEY, {})
    if not isinstance(account, dict) or not isinstance(account.get('inactive', {}), dict):
        raise ValueError('Unexpected account state format; no changes made.')
    for name, item in account.get('inactive', {}).items():
        if not isinstance(item, dict) or not isinstance(item.get('globals'), dict):
            raise ValueError('Unexpected saved profile format; no changes made.')
        yield name, item['globals']


def patched_state(original):
    scopes = list(profiles(original))
    catalog = {}
    for _, scope in scopes:
        entries = scope.get('local-projects', {})
        if not isinstance(entries, dict):
            raise ValueError('Unexpected local project format; no changes made.')
        for ident, project in entries.items():
            if (not isinstance(project, dict) or project.get('id') != ident
                    or not isinstance(project.get('name'), str)
                    or not isinstance(project.get('rootPaths'), list)
                    or not all(isinstance(p, str) for p in project['rootPaths'])):
                raise ValueError('Unexpected project record; no changes made.')
            previous = catalog.get(ident)
            if previous is None or project.get('updatedAt', 0) > previous.get('updatedAt', 0):
                catalog[ident] = copy.deepcopy(project)
    if not catalog:
        raise ValueError('No saved local projects found; no changes made.')

    # Prefer the currently visible order, then the most complete saved order.
    ordered_scopes = [scopes[0]] + sorted(scopes[1:],
        key=lambda s: len(s[1].get('project-order', [])), reverse=True)
    order = []
    for _, scope in ordered_scopes:
        for ident in scope.get('project-order', []):
            if ident in catalog and ident not in order:
                order.append(ident)
    order.extend(ident for ident in catalog if ident not in order)

    mappings = {}
    for _, scope in scopes:
        hosts = scope.get('app-server-project-id-by-legacy-project-id-by-host', {})
        if not isinstance(hosts, dict):
            raise ValueError('Unexpected project mapping format; no changes made.')
        for host, entries in hosts.items():
            if not host.startswith('local:'):
                continue
            for ident, target in entries.items():
                if ident not in catalog:
                    continue
                old = mappings.setdefault(host, {}).get(ident)
                if old is not None and old != target:
                    raise ValueError('Conflicting local project IDs; manual review required.')
                mappings[host][ident] = target

    result = copy.deepcopy(original)
    counts = []
    for label, scope in profiles(result):
        before = len(scope.get('local-projects', {}))
        scope['local-projects'] = copy.deepcopy(catalog)
        scope['project-order'] = list(order)
        if mappings:
            hosts = scope.setdefault('app-server-project-id-by-legacy-project-id-by-host', {})
            for host, entries in mappings.items():
                hosts.setdefault(host, {}).update(entries)
        counts.append({'profile': label, 'before': before, 'after': len(catalog)})

    # Assert that every non-catalog value remains identical, including account
    # identities, atoms, cloud state, queued messages and permission settings.
    def without_catalog(value):
        value = copy.deepcopy(value)
        for _, scope in profiles(value):
            for key in ALLOWED:
                scope.pop(key, None)
        return value
    if without_catalog(original) != without_catalog(result):
        raise AssertionError('Unexpected change outside local project fields.')
    return result, counts


def running_apps():
    run = subprocess.run(['tasklist.exe', '/FO', 'CSV', '/NH'],
                         capture_output=True, check=True)
    output = run.stdout.decode('mbcs', errors='replace')
    return sorted({row[0] for row in csv.reader(io.StringIO(output))
                   if row and row[0].lower() in ('codex.exe', 'chatgpt.exe')})


def atomic_apply(path, original_bytes, result, backup_dir):
    # Check immediately before writing so unrelated concurrent edits are not lost.
    if path.read_bytes() != original_bytes:
        raise RuntimeError('Configuration changed during preparation. Run again after exiting the app.')
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_dir / ('global-state-' + stamp + '.json')
    with backup.open('xb') as stream:
        stream.write(original_bytes)
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    temporary = path.with_name(path.name + '.project-restore-' + stamp + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original_bytes:
            raise RuntimeError('Configuration changed. Original file left untouched.')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if json.loads(path.read_bytes()) != result:
        raise RuntimeError('Post-write verification failed. Keep the app closed and use the backup.')
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--state', type=Path,
                        default=Path.home() / '.codex' / '.codex-global-state.json')
    args = parser.parse_args()
    if args.apply:
        if os.name != 'nt':
            raise RuntimeError('This recovery launcher is for Windows.')
        print('Please fully exit Codex / ChatGPT. Waiting up to 10 minutes...', flush=True)
        deadline = time.monotonic() + 600
        while running_apps():
            if time.monotonic() >= deadline:
                raise RuntimeError('App still running. No configuration changes made.')
            time.sleep(2)
        time.sleep(2)
        if running_apps():
            raise RuntimeError('App reopened. Close it and run recovery again.')

    original_bytes = args.state.read_bytes()
    original = json.loads(original_bytes)
    result, counts = patched_state(original)
    print(json.dumps({'mode': 'apply' if args.apply else 'preview',
                      'profiles': len(counts),
                      'local_projects': len(result['local-projects']),
                      'previous_counts': [c['before'] for c in counts]}, ensure_ascii=False))
    if not args.apply:
        return
    if running_apps():
        raise RuntimeError('App reopened. No configuration changes made.')
    if result == original:
        print('All saved account profiles already have the same project catalog.')
    else:
        backup = atomic_apply(args.state, original_bytes, result,
                              Path(__file__).resolve().parent / 'project-backups')
        print('SUCCESS: local project catalogs restored. Backup: ' + str(backup))
    print('You can now reopen Codex. New accounts or newly added projects require running this tool again.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
