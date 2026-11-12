import shlex,subprocess
from pathlib import Path
root=Path('.runtime/hydra_ws').resolve();out=Path('runs/hydra-objectnav/B1-stability-20261107/native').resolve();flags={}
for line in (root/'build/hydra/CMakeFiles/hydra.dir/flags.make').read_text().splitlines():
 if ' = ' in line:
  k,v=line.split(' = ',1);flags[k]=shlex.split(v)
paths=[str(out)]+[str(p) for p in (root/'install').glob('*/lib')]+[str(root/'sysroot/usr/lib/x86_64-linux-gnu'),str(root/'sysroot/opt/ros/jazzy/lib/x86_64-linux-gnu')]
cmd=['/usr/bin/c++',*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'tools/native/hydra_room_stability/test_native.cpp','-o',str(out/'test_native'),'-L'+str(out),'-lhydra','-L'+str(root/'install/spark_dsg/lib'),'-lspark_dsg','-Wl,-rpath-link,'+':'.join(paths),'-Wl,--disable-new-dtags,-rpath,'+':'.join(paths)]
p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True);(out/'test-build.log').write_text(p.stdout);raise SystemExit(p.returncode)
