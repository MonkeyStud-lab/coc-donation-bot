#!/usr/bin/env python3
"""Offline blank-profile acceptance for a built image; never connects to Android."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def verify(app):
    from coc_bot.attack.army import UnitCatalog

    app = Path(app)
    spec = importlib.util.spec_from_file_location('image_entrypoint', app/'packaging/casaos/entrypoint.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    manifest = json.loads((app/'data/icons/manifest.json').read_text())
    required = {'troops/electro_dragon.webp', 'spells/rage_spell.webp'}
    if manifest.get('missing_core') or not required.issubset(manifest.get('files', {})):
        raise ValueError('Image is missing required automatic-attack artwork')
    with tempfile.TemporaryDirectory(prefix='coc-image-check-') as temporary:
        profile = Path(temporary)/'profile'
        entry.seed_profile(app, profile)
        for name, digest in manifest['files'].items():
            path = profile/'data/icons'/name
            if not path.resolve().is_relative_to((profile/'data/icons').resolve()):
                raise ValueError('Artwork manifest path escapes the icon directory')
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Fresh-profile artwork checksum failed: '+name)
        catalog = UnitCatalog(profile/'data/icons')
        identities = {item[0] for item in catalog.templates}
        if not {'electro_dragon', 'rage_spell'}.issubset(identities):
            raise ValueError('Required artwork cannot be loaded by the army recognizer')
        if (profile/'data/calibrated.yaml').exists():
            raise ValueError('An image must not ship private calibration')
        from coc_bot.web.live import VERSION, SERVER_SHA256
        gesture = profile/'data/live'/('scrcpy-server-v'+VERSION)
        if hashlib.sha256(gesture.read_bytes()).hexdigest() != SERVER_SHA256:
            raise ValueError('Gesture server was not seeded correctly')
        target = profile/'data/icons/troops/electro_dragon.webp'
        target.write_bytes(b'preserve-user-artwork')
        entry.seed_profile(app, profile)
        if target.read_bytes() != b'preserve-user-artwork':
            raise ValueError('Profile seeding overwrote user artwork')
        return {'blank_profile': True, 'icons': len(manifest['files']),
                'core_recognizer_artwork': True, 'gesture_server_verified': True,
                'existing_artwork_preserved': True, 'android_inputs': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path('/app'))
    args = parser.parse_args()
    print(json.dumps(verify(args.app), indent=2))


if __name__ == '__main__':
    main()
