#!/usr/bin/env python3
"""Compile only the replacement RoomFinder TU and link a private Hydra DSO."""
import json, shlex, subprocess
from pathlib import Path
root=Path('.runtime/hydra_ws').resolve(); build=root/'build/hydra'; out=Path('runs/hydra-objectnav/B1-stability-20261107/native').resolve(); out.mkdir(parents=True,exist_ok=True)
flags={}
for line in (build/'CMakeFiles/hydra.dir/flags.make').read_text().splitlines():
 if ' = ' in line:
  k,v=line.split(' = ',1); flags[k]=shlex.split(v)
obj=out/'room_finder.cpp.o'; source=Path('tools/native/hydra_room_stability/room_finder.cpp').resolve()
compile=['/usr/bin/c++',*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',str(source),'-o',str(obj)]
link=shlex.split((build/'CMakeFiles/hydra.dir/link.txt').read_text()); link[link.index('-o')+1]=str(out/'libhydra.so'); link=[str(obj) if x=='CMakeFiles/hydra.dir/src/rooms/room_finder.cpp.o' else x for x in link]
(out/'build-commands.json').write_text(json.dumps([compile,link],indent=2)+'\n')
with (out/'build.log').open('w') as log:
 for cmd,cwd in ((compile,Path.cwd()),(link,build)):
  p=subprocess.run(cmd,cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
  if p.returncode: (out/'build.exit').write_text(str(p.returncode)+'\n'); raise SystemExit(p.returncode)
(out/'build.exit').write_text('0\n')
