#!/usr/bin/env python3
"""Link the room-stability implementation against the isolated journal objects."""
import argparse
from hashlib import file_digest
import json
from pathlib import Path
import shlex
import shutil
import subprocess

import yaml


def sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def build(args):
    build_root = args.build.resolve(strict=True)
    binding = args.binding.resolve(strict=True)
    if sha(binding) != args.binding_sha256:
        raise ValueError('companion binding SHA does not match')
    if binding.parent != (build_root / 'python'):
        raise ValueError('use the binding from the same isolated build')
    args.out.mkdir(parents=True, exist_ok=False)
    output = args.out.resolve()
    metadata = build_root / 'CMakeFiles/hydra.dir'
    source = output / 'room_finder.cpp'
    source.write_text(
        Path('tools/native/hydra_room_stability/room_finder.cpp').read_text()
        + f'\nextern "C" const char* nsn_object_journal_binding_sha256() '
          f'{{ return "{args.binding_sha256}"; }}\n'
    )
    flags = {}
    for line in (metadata / 'flags.make').read_text().splitlines():
        if ' = ' in line:
            key, value = line.split(' = ', 1)
            flags[key] = shlex.split(value)
    obj = output / 'room_finder.cpp.o'
    library = output / 'libhydra.so'
    link = shlex.split((metadata / 'link.txt').read_text())
    old_obj = 'CMakeFiles/hydra.dir/src/rooms/room_finder.cpp.o'
    link[link.index(old_obj)] = str(obj)
    link[link.index('-o') + 1] = str(library)
    compile_args = [link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'],
                    '-c', str(source), '-o', str(obj)]
    (output / 'commands.json').write_text(json.dumps([compile_args, link], indent=2) + '\n')
    subprocess.run(compile_args, cwd=build_root, check=True)
    subprocess.run(link, cwd=build_root, check=True)

    config = output / 'config'
    shutil.copytree(args.config_root, config)
    dataset = config / 'datasets/neusymnav.yaml'
    recipe = yaml.safe_load(dataset.read_text())
    library_sha = sha(library)
    recipe['neusymnav_room_stability'] = dict(enabled=True, library_path=str(library),
                                             library_sha256=library_sha)
    dataset.write_text(yaml.safe_dump(recipe, sort_keys=False))
    print(json.dumps(dict(native_binding_sha256=args.binding_sha256, native_library_sha256=library_sha,
                          dataset_sha256=sha(dataset), config_root=str(config))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'binding', 'config-root', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--binding-sha256', required=True)
    build(parser.parse_args())


if __name__ == '__main__':
    main()
