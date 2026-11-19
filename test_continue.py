import contextlib, importlib.util, io, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
root=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('runner_test',os.environ.get('TARGET_RUNNER',str(root/'hardware_runner.py')));r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class Function:
 def __init__(self,rc,events):self.rc=rc;self.events=events
 def __call__(self,ini,firmware,callback):
  for event in self.events: callback(*event)
  return self.rc
class DLL:
 def __init__(self,rc,events): self.MatFwDownload=Function(rc,events)
class Tests(unittest.TestCase):
 def firmware(self,rc,events):
  h=r.Hardware.__new__(r.Hardware);h.dev=None
  with patch.object(r.c,'WinDLL',return_value=DLL(rc,events)),contextlib.redirect_stdout(io.StringIO()):return h.run({'type':'firmware','params':{'ini':'a','firmware':'b'}})
 def test_100_percent_then_error_completed_with_warning(self):
  x=self.firmware(3,[(1,100,0),(3,100,-13)]);self.assertIsInstance(x,dict);self.assertIn('100%',x['message']);self.assertIn('-13',x['message']);self.assertIn('未确认',x['message']);self.assertEqual(x['sdk_status'],3);self.assertEqual(x['sdk_error'],-13)
 def test_100_then_failure_no_progress_also_completed(self):
  x=self.firmware(0,[(1,100,0),(3,-1,-13)]);self.assertIn('-13',x['message'])
 def test_failure_before_100(self):
  with self.assertRaises(RuntimeError):self.firmware(3,[(1,90,0),(3,90,-13)])
 def test_true_success(self):
  self.assertEqual(self.firmware(2,[(1,100,0),(2,100,0)]),'固件下载回调报告成功')
 def test_nonzero_without_terminal_fails(self):
  with self.assertRaises(RuntimeError):self.firmware(-2,[])
 def test_failed_open_does_not_leave_device_handle(self):
  class Device:
   def get_device(self,n):return 42
   def device_setConfigure(self,h,p):pass
   def device_open(self,h):return False
   def device_close(self,h):raise AssertionError('not opened')
  h=r.Hardware.__new__(r.Hardware);h.dev=None;h.d=Device()
  with patch.object(r.time,'sleep',lambda _:None):
   with self.assertRaisesRegex(RuntimeError,'设备打开失败'):h.run({'type':'power_on','params':{'ini':'x'}})
  self.assertIsNone(h.dev)
 def test_failed_video_closes_open_device(self):
  class Device:
   closed=[]
   def get_device(self,n):return 42
   def device_setConfigure(self,h,p):pass
   def device_open(self,h):return True
   def device_open_video(self,h):return False
   def device_close(self,h):self.closed.append(h)
  h=r.Hardware.__new__(r.Hardware);h.dev=None;h.d=Device()
  with patch.object(r.time,'sleep',lambda _:None):
   with self.assertRaisesRegex(RuntimeError,'视频流打开失败'):h.run({'type':'power_on','params':{'ini':'x'}})
  self.assertIsNone(h.dev);self.assertEqual(h.d.closed,[42])
 def test_critical_failures_continue(self):
  calls=[]
  class Fake:
   def run(self,n):
    calls.append(n['type'])
    if n['type'] in ('relay_off','power_on','capture'):raise RuntimeError('模拟错误')
    return 'ok'
   def close(self):calls.append('close')
  with tempfile.TemporaryDirectory() as td:
   ini=pathlib.Path(td)/'a.ini';ini.write_text('x'); p=pathlib.Path(td)/'case.json'
   specs=[('relay_off',{'port':'COM7','channel':0}),('power_on',{'ini':str(ini)}),('capture',{'output':'x'}),('power_off',{}),('wait',{'seconds':0})]
   nodes=[{'id':str(i),'type':typ,'params':params} for i,(typ,params) in enumerate(specs)];p.write_text(json.dumps({'version':2,'nodes':nodes,'edges':[{'from':str(i),'to':str(i+1)} for i in range(len(nodes)-1)]}),encoding='utf8');out=io.StringIO()
   with patch.object(r,'Hardware',Fake),patch.object(r.time,'sleep',lambda x:None),contextlib.redirect_stdout(out):status=r.main(p)
  self.assertEqual(calls,['relay_off','power_on','capture','power_off','wait','close']);self.assertEqual(status,2)
  events=[json.loads(x[len('@@CANVAS_EVENT@@'):]) for x in out.getvalue().splitlines() if x.startswith('@@CANVAS_EVENT@@')];errs=[x for x in events if x['event']=='step_error'];self.assertEqual(len(errs),3);self.assertTrue(all(x['continued'] for x in errs));self.assertEqual(events[-1]['failed_count'],3)
if __name__=='__main__':unittest.main(verbosity=2)
