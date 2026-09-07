"""Fingerprint the files actually packaged into the application image."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_manifest(root=ROOT):
    paths = [root/'requirements.txt', root/'Dockerfile']
    for directory in ('src', 'static', 'licenses'):
        paths.extend(p for p in (root/directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(set(paths)) if p.is_file()}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'source_fingerprint': 'sha256:' + digest, 'files': files}


def write_manifest(root=ROOT):
    data = source_manifest(root)
    data['base_git_sha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    data['is_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip())
    (root/'build_manifest.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    return data


def verify_manifest(root=ROOT):
    actual = source_manifest(root)
    path = root/'build_manifest.json'
    expected = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {**actual, 'base_git_sha': expected.get('base_git_sha', 'unknown'),
            'is_dirty': expected.get('is_dirty'),
            'manifest_verified': bool(expected) and expected.get('files') == actual['files']
              and expected.get('source_fingerprint') == actual['source_fingerprint']}


if __name__ == '__main__':
    print(json.dumps(write_manifest(), indent=2))
