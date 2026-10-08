#!/usr/bin/env python3
import os,sys,tempfile,time,subprocess
sys.path.insert(0,os.path.dirname(__file__));from make_ipk_fixtures import ipk
r=os.path.dirname(os.path.dirname(__file__));h=os.path.join(r,'build','ipk_closure.py')
names='kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim libmbim mbim-utils libqmi qmi-utils modemmanager dw5934e-autonet'.split()

def fixture_set(d,now,wrong_arch=None):
 fs=[]
 for n in names:
  f=os.path.join(d,n+'.ipk')
  ipk(f,n,arch='wrongarch' if n==wrong_arch else 'aarch64',depends='kernel (= 6.6.1~x)' if n.startswith('kmod-') else '')
  os.utime(f,(now+2 if n in ('modemmanager','dw5934e-autonet') else now-20,)*2);fs.append(f)
 return fs

def command(d,now,fs):
 return [sys.executable,h,'--out',os.path.join(d,'out'),'--arch','aarch64','--kernel','6.6.1~x','--fresh-after',str(now),'--required']+names+['--']+fs

# Existing dependencies may predate the build stamp; only MM and AutoNet require freshness.
with tempfile.TemporaryDirectory() as d:
 now=time.time();fs=fixture_set(d,now);cmd=command(d,now,fs)
 q=subprocess.run(cmd,capture_output=True,text=True);assert q.returncode==0,q.stderr
 ipk(os.path.join(d,'kmod-mhi-bus.ipk'),'kmod-mhi-bus',depends='kernel (= bad)');os.utime(os.path.join(d,'kmod-mhi-bus.ipk'),(now-20,now-20))
 q=subprocess.run(cmd,capture_output=True,text=True);assert q.returncode!=0 and 'required package output missing: kmod-mhi-bus' in q.stderr,q.stderr

# A candidate of the wrong architecture alone must not satisfy a dependency.
with tempfile.TemporaryDirectory() as d:
 now=time.time();fs=fixture_set(d,now,'libmbim');q=subprocess.run(command(d,now,fs),capture_output=True,text=True)
 assert q.returncode!=0 and 'required package output missing: libmbim' in q.stderr,q.stderr

# Different-mtime non-identical IPKs for a package are still an ambiguity: mtime
# is not provenance and must not choose a winner.
with tempfile.TemporaryDirectory() as d:
 now=time.time();fs=fixture_set(d,now)
 alt=os.path.join(d,'libmbim-alternative.ipk');ipk(alt,'libmbim',depends='libgcc');os.utime(alt,(now-200,now-200));fs.append(alt)
 q=subprocess.run(command(d,now,fs),capture_output=True,text=True)
 assert q.returncode!=0 and 'ambiguous current candidate: libmbim' in q.stderr,q.stderr

print('PASS: exact-tree selection, wrong ABI/arch rejection, and different-mtime ambiguity rejection')
