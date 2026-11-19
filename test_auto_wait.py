import contextlib, importlib.util, io, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
root=pathlib.Path(__file__).resolve().parent; sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('runner_test',os.environ.get('TARGET_RUNNER',str(root/'hardware_runner.py'))); r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
class Clock:
 def __init__(self): self.now=0.; self.sleeps=[]
 def monotonic(self): return self.now
 def sleep(self,s): self.sleeps.append(round(s,5)); self.now+=s
class TimingTests(unittest.TestCase):
 def execute(self,specs,fail=None):
  clock=Clock(); calls=[]
  class Fake:
   def run(self,n):
    calls.append((n['type'],round(clock.now,5)))
    if n['type']=='wait': clock.sleep(n['params']['seconds'])
    if n['type']==fail: raise RuntimeError('simulated')
    return 'ok'
   def close(self): pass
  with tempfile.TemporaryDirectory() as td:
   ini=pathlib.Path(td)/'x.ini'; ini.write_text('x'); p=pathlib.Path(td)/'test.json'
   nodes=[]
   for i,(typ,params) in enumerate(specs):
    params=dict(params)
    if typ=='power_on':params['ini']=str(ini)
    nodes.append({'id':str(i),'type':typ,'params':params})
   p.write_text(json.dumps({'version':2,'nodes':nodes,'edges':[{'from':str(i),'to':str(i+1)} for i in range(len(nodes)-1)]}),encoding='utf8')
   out=io.StringIO()
   with patch.object(r,'Hardware',Fake),patch.object(r.time,'monotonic',clock.monotonic),patch.object(r.time,'sleep',clock.sleep),contextlib.redirect_stdout(out): status=r.main(p)
  return calls,clock.sleeps,out.getvalue(),status
 def test_relay_waits_count_explicit(self):
  relay={'port':'COM7','channel':0}
  calls,sleeps,out,status=self.execute([('relay_off',relay),('wait',{'seconds':1}),('relay_on',relay),('wait',{'seconds':2}),('power_on',{}),('power_off',{})])
  self.assertEqual(calls,[('relay_off',0),('wait',0),('relay_on',5),('wait',5),('power_on',13),('power_off',13.07)])
  self.assertIn('自动稳定等待',out); self.assertEqual(status,0)
 def test_implicit_relay_guards(self):
  relay={'port':'COM7','channel':0}
  calls,sleeps,out,status=self.execute([('relay_off',relay),('relay_on',relay),('power_on',{}),('power_off',{})])
  self.assertEqual(calls,[('relay_off',0),('relay_on',5),('power_on',13),('power_off',13.07)]); self.assertEqual(status,0)
 def test_long_explicit_wait_not_doubled(self):
  relay={'port':'COM7','channel':0}
  calls,sleeps,out,status=self.execute([('relay_on',relay),('wait',{'seconds':10}),('relay_off',relay)])
  self.assertEqual(calls,[('relay_on',0),('wait',0),('relay_off',10)]); self.assertEqual(sleeps,[10,5])
 def test_short_wait_counted_and_soft_failure_continues(self):
  p={'slave':'0x40','register':'0xcc','address_bits':16,'data_bits':32}; q={'output':'x'}
  calls,sleeps,out,status=self.execute([('power_on',{}),('i2c_read',p),('wait',{'seconds':0.07}),('capture',q),('power_off',{})],fail='i2c_read')
  self.assertEqual(calls,[('power_on',0),('i2c_read',0.07),('wait',0.07),('capture',0.14),('power_off',0.21)]);self.assertEqual(status,2)
 def test_final_relay_cools_down_before_repeat(self):
  relay={'port':'COM7','channel':0}; calls,sleeps,out,status=self.execute([('relay_on',relay)])
  self.assertEqual(calls,[('relay_on',0)]); self.assertEqual(sleeps,[8])
if __name__=='__main__':unittest.main(verbosity=2)
