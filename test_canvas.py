import json, pathlib, tempfile, types, unittest
import app
from case_model import execution_order,load_case,resolve_paths,validate_steps

class CanvasTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.w=app.App();self.w.project=pathlib.Path(self.temp.name);self.w.folder=self.w.project;self.w.refresh();self.w.update();self.w.new_case();self.w.update()
 def tearDown(self):self.w.destroy();self.temp.cleanup()
 def event(self,name,x,y,**extra):
  cv=self.w.canvas; x=round(x-cv.canvasx(0));y=round(y-cv.canvasy(0));cv.event_generate(name,x=x,y=y,**extra);self.w.update()
 def test_copy_link_delete_and_persist(self):
  w=self.w;w.add('wait',50,100);w.param_vars['seconds'].set('4');w.copy_node();w.paste_node(350,100);w.update()
  self.assertEqual(w.nodes[1]['params']['seconds'],4);self.assertNotEqual(w.nodes[0]['id'],w.nodes[1]['id']);self.assertFalse(w.edges)
  self.event('<ButtonPress-1>',230,142);self.event('<B1-Motion>',300,142);self.event('<ButtonRelease-1>',350,142)
  self.assertEqual(len(execution_order(load_case(w.case))),2)
  self.event('<ButtonPress-1>',290,142);self.assertEqual(w.selected_edge,0);w.delete_selection();self.assertEqual(load_case(w.case)['edges'],[])
 def test_shortcut_copy_paste(self):
  w=self.w;w.add('i2c_read',50,100);w.update();w.canvas.focus_force();w.update()
  w.canvas.event_generate('<Control-KeyPress-c>');w.update();w.canvas.event_generate('<Control-KeyPress-v>');w.update()
  self.assertEqual(len(w.nodes),2);self.assertEqual(w.nodes[0]['params'],w.nodes[1]['params']);self.assertNotEqual(w.nodes[0]['id'],w.nodes[1]['id'])
 def test_right_click_edge_delete(self):
  w=self.w;w.add('wait',50,100);w.add('wait',350,100);w.update()
  self.event('<ButtonPress-1>',230,142);self.event('<ButtonRelease-1>',350,142)
  class Menu:
   last=None
   def __init__(self,*args,**kwargs):self.commands=[];Menu.last=self
   def add_command(self,**kwargs):self.commands.append(kwargs)
   def add_separator(self):pass
   def tk_popup(self,*args):pass
   def grab_release(self):pass
  old=app.tk.Menu;app.tk.Menu=Menu
  try:
   cv=w.canvas;x=round(290-cv.canvasx(0));y=round(142-cv.canvasy(0));w.context_menu(types.SimpleNamespace(x=x,y=y,x_root=0,y_root=0))
   next(c['command'] for c in Menu.last.commands if c['label']=='删除这条连线')();self.assertEqual(w.edges,[])
  finally:app.tk.Menu=old
 def test_pan_zoom_and_drag_in_world_coordinates(self):
  w=self.w;w.add('wait',50,100);w.update();cv=w.canvas
  x,y=260,240; before=(cv.canvasx(x)/w.zoom,cv.canvasy(y)/w.zoom)
  cv.event_generate('<MouseWheel>',x=x,y=y,delta=120);w.update();after=(cv.canvasx(x)/w.zoom,cv.canvasy(y)/w.zoom)
  self.assertAlmostEqual(before[0],after[0],delta=2);self.assertAlmostEqual(before[1],after[1],delta=2)
  z=w.zoom;self.event('<ButtonPress-1>',100*z,115*z);self.event('<B1-Motion>',120*z,135*z);self.event('<ButtonRelease-1>',120*z,135*z)
  self.assertEqual((w.nodes[0]['x'],w.nodes[0]['y']),(70,120))
  old=cv.canvasx(0);cv.event_generate('<ButtonPress-1>',x=500,y=400);cv.event_generate('<B1-Motion>',x=460,y=400);cv.event_generate('<ButtonRelease-1>',x=460,y=400);w.update();self.assertNotEqual(old,cv.canvasx(0))
 def test_zoomed_connection_and_cycle_rejection(self):
  w=self.w;w.add('wait',50,100);w.add('wait',350,100);w.update();w.zoom_center(1.12);w.update();z=w.zoom
  self.event('<ButtonPress-1>',230*z,142*z);self.event('<ButtonRelease-1>',350*z,142*z);self.assertEqual(len(w.edges),1)
  self.event('<ButtonPress-1>',530*z,142*z);self.event('<ButtonRelease-1>',50*z,142*z);self.assertEqual(len(w.edges),1)
  self.assertIn('循环',w.status.cget('text'));w.fit_canvas();w.update();self.assertGreater(w.zoom,0)
 def test_run_uses_snapshot_and_keeps_full_diagnostic_log(self):
  import time
  w=self.w;w.add('wait',50,50)
  class FakeProcess:
   def __init__(self,args,**kw):self.args=args;self.stdout=iter(['[warning] [StructuredException.cpp:183] SetUnhandledExceptionFilter...\n','真实流程完成\n'])
   def wait(self):return 0
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   w.run_real();limit=time.monotonic()+3
   while w.process and time.monotonic()<limit:w.update();time.sleep(.02)
   self.assertIsNone(w.process);self.assertIn('运行成功',w.status.cget('text'))
   logs=list((w.project/'测试结果').rglob('底层完整日志.log'));snapshots=list((w.project/'测试结果').rglob('执行快照.json'))
   self.assertEqual(len(logs),1);self.assertEqual(len(snapshots),1);self.assertIn('StructuredException.cpp:183',logs[0].read_text(encoding='utf-8'))
   self.assertNotIn('StructuredException.cpp:183',w.log.get('1.0','end'))
  finally:app.subprocess.Popen=old
 def test_preflight_user_case_and_invalid_sequence(self):
  p=pathlib.Path('dist/设备测试画布/项目/test1/Case 001.case.json')
  if p.exists():validate_steps(execution_order(resolve_paths(load_case(p),p,app.ROOT)))
  with self.assertRaisesRegex(ValueError,'设备上电'):
   validate_steps([{'type':'i2c_read','params':{'slave':'0x40','register':'0xcc','address_bits':16,'data_bits':16}}])
 def test_readable_i2c_and_capture_logs_and_paths(self):
  w=self.w;w.add('wait',10,10)
  w.render_event({'event':'step_start','index':4,'total':9,'type':'i2c_read','params':{'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':16,'expected':''}})
  w.render_event({'event':'step_done','index':4,'type':'i2c_read','message':'I²C 读取 0xCC = 0x857B','elapsed':.1})
  w.render_event({'event':'step_start','index':5,'total':9,'type':'i2c_read','params':{'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':16,'expected':''}})
  w.render_event({'event':'step_done','index':5,'type':'i2c_read','message':'I²C 读取 0xCC = 0x27C','elapsed':.1})
  path=str(w.project/'out'/'frame.yuyv');preview=str(w.project/'out'/'frame.png')
  w.render_event({'event':'step_done','type':'capture','elapsed':.1,'message':'ok','artifacts':{'raw':path,'preview':preview}})
  log=w.log.get('1.0','end');self.assertIn('04 / 09',log);self.assertIn('05 / 09',log);self.assertIn('0x857B',log);self.assertIn('0x27C',log);self.assertIn('0x40',log);self.assertIn('未设置期望值',log)
  self.assertIn(path,log);self.assertEqual(w.last_image_dir,pathlib.Path(path).parent);self.assertEqual(w.last_preview,pathlib.Path(preview))
 def test_run_directory_variable_and_custom_output(self):
  from case_model import resolve_paths
  case={'nodes':[{'type':'capture','params':{'output':'${RUNDIR}/图片/capture'}},{'type':'capture','params':{'output':'D:/custom/capture'}}],'edges':[]}
  resolved=resolve_paths(case,self.w.case,app.ROOT,self.w.project/'results'/'run1')
  self.assertEqual(resolved['nodes'][0]['params']['output'],str((self.w.project/'results'/'run1'/'图片'/'capture').resolve()))
  self.assertEqual(resolved['nodes'][1]['params']['output'],'D:/custom/capture')
 def test_structured_run_archives_readable_and_raw_logs(self):
  import time
  w=self.w;w.add('wait',20,20)
  records=[{'event':'step_start','index':1,'total':1,'type':'i2c_read','params':{'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':16,'expected':''}},{'event':'step_done','index':1,'type':'i2c_read','elapsed':0.2,'message':'I²C 读取 0xCC = 0x857B'}]
  class FakeProcess:
   def __init__(self,args,**kw):self.stdout=iter(['[2026-11-16 02:11:32] [info] [dllmain.cpp:17]\n']+['@@CANVAS_EVENT@@'+json.dumps(record,ensure_ascii=False)+'\n' for record in records])
   def wait(self):return 0
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   w.run_real();limit=time.monotonic()+3
   while w.process and time.monotonic()<limit:w.update();time.sleep(.02)
   self.assertIsNone(w.process);out=w.log.get('1.0','end');self.assertIn('0x857B',out);self.assertIn('寄存器 0x00cc',out);self.assertNotIn('dllmain.cpp',out)
   self.assertIn('0x857B',(w.current_run_dir/'日志'/'执行记录.txt').read_text(encoding='utf8'));self.assertIn('dllmain.cpp',(w.current_run_dir/'日志'/'底层完整日志.log').read_text(encoding='utf8'))
  finally:app.subprocess.Popen=old
 def test_log_popup_and_result_open_actions(self):
  w=self.w;w.log_append('测试显示','heading');w.expand_log();w.update();popups=[c for c in w.winfo_children() if isinstance(c,app.tk.Toplevel)]
  self.assertTrue(popups);self.assertIn('测试显示',next(x for x in popups[-1].winfo_children() if isinstance(x,app.tk.Text)).get('1.0','end'))
  popups[-1].destroy();directory=w.project/'images';directory.mkdir();preview=directory/'capture.png';preview.write_bytes(b'x')
  w.current_run_dir=w.project;w.last_image_dir=directory;w.last_preview=preview;opened=[];old=app.os.startfile;old_view=w.show_large_image;app.os.startfile=lambda p:opened.append(str(p));w.show_large_image=lambda p:opened.append(str(p))
  try:w.open_run_dir();w.open_image_dir();w.open_preview()
  finally:app.os.startfile=old;w.show_large_image=old_view
  self.assertEqual(opened,[str(w.project),str(directory),str(preview)])
 def test_repeated_runs_keep_separate_result_folders(self):
  import time
  w=self.w;w.add('wait',10,10)
  class FakeProcess:
   def __init__(self,args,**kw):self.stdout=iter([])
   def wait(self):return 0
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   dirs=[]
   for _ in range(2):
    w.run_real();deadline=time.monotonic()+3
    while w.process and time.monotonic()<deadline:w.update();time.sleep(.02)
    self.assertIsNone(w.process);dirs.append(w.current_run_dir)
   self.assertNotEqual(*dirs)
   for d in dirs:self.assertTrue((d/'日志'/'执行记录.txt').is_file());self.assertTrue((d/'日志'/'底层完整日志.log').is_file());self.assertTrue((d/'配置'/'执行快照.json').is_file())
  finally:app.subprocess.Popen=old
 def test_fractional_wait_new_and_legacy_nodes(self):
  import hardware_runner as runner
  w=self.w;w.add('wait',20,20);w.param_vars['seconds'].set('0.07');self.assertTrue(w.apply());self.assertTrue(w.save());self.assertEqual(load_case(w.case)['nodes'][0]['params']['seconds'],0.07)
  # Existing Case files used integers; changing an old node must also accept decimals.
  w.nodes[0]['params']['seconds']=1;w.show_params();w.param_vars['seconds'].set('0.07');self.assertTrue(w.apply());self.assertEqual(w.nodes[0]['params']['seconds'],0.07)
  observed=[];old=runner.time.sleep;runner.time.sleep=lambda seconds:observed.append(seconds)
  try:
   h=object.__new__(runner.Hardware);h.run({'type':'wait','params':w.nodes[0]['params']})
  finally:runner.time.sleep=old
  self.assertEqual(observed,[0.07]);validate_steps(execution_order(load_case(w.case)))
  w.render_event({'event':'step_start','index':1,'total':1,'type':'wait','params':{'seconds':0.07}});w.render_event({'event':'step_done','index':1,'type':'wait','elapsed':0.0701,'message':'等待完成'})
  log=w.log.get('1.0','end');self.assertIn('70 毫秒',log);self.assertIn('70.1 毫秒',log)
 def test_i2c_format_selector_maps_to_sdk_bits(self):
  w=self.w;w.add('i2c_read',20,20);w.update()
  combo=next(c for c in w.param_frame.winfo_children() if isinstance(c,app.ttk.Combobox))
  self.assertEqual(combo.get(),'A2D4');combo.set('A2D2');combo.event_generate('<<ComboboxSelected>>');w.update();self.assertTrue(w.apply())
  self.assertEqual(w.nodes[0]['params']['address_bits'],16);self.assertEqual(w.nodes[0]['params']['data_bits'],16)
  combo.set('A2D4');combo.event_generate('<<ComboboxSelected>>');w.update();self.assertTrue(w.apply());self.assertEqual(w.nodes[0]['params']['data_bits'],32)
 def test_i2c_display_zero_padding_and_sdk_bit_lengths(self):
  import ctypes,hardware_runner as runner
  class DLL:
   def __init__(self):self.calls=[]
   def device_I2C_Read(self,handle,slave,reg,ptr,ab,db):
    self.calls.append((slave,reg,ab,db));ctypes.cast(ptr,ctypes.POINTER(ctypes.c_uint32)).contents.value=0x2345;return True
   def device_I2C_Write(self,handle,slave,reg,value,ab,db):self.calls.append((slave,reg,value,ab,db));return True
  h=object.__new__(runner.Hardware);h.dev=1;h.d=DLL()
  params={'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':32}
  self.assertEqual(h.run({'type':'i2c_read','params':params}),'[r] 0x00cc 0x00002345');self.assertEqual(h.d.calls[-1],(0x40,0xcc,16,32))
  params['data_bits']=16;params['value']='0x12';self.assertEqual(h.run({'type':'i2c_write','params':params}),'[w] 0x00cc 0x0012');self.assertEqual(h.d.calls[-1],(0x40,0xcc,0x12,16,16))
 def test_copy_case_is_independent_and_preserves_original(self):
  w=self.w;w.add('wait',10,10);w.param_vars['seconds'].set('0.07');original=w.case;w.tree.selection_set(str(original));w.update()
  self.assertTrue(w.copy_case());w.paste_case();w.update();first=w.case
  self.assertNotEqual(first,original);self.assertEqual(load_case(first)['nodes'][0]['params']['seconds'],0.07);self.assertEqual(load_case(original),load_case(first))
  w.paste_case();w.update();second=w.case;self.assertNotEqual(first,second);self.assertTrue(original.exists())
  w.nodes[0]['params']['seconds']=3;w.selected=None;w.persist();self.assertEqual(load_case(original)['nodes'][0]['params']['seconds'],0.07)
 def test_fit_arranges_real_case_without_changing_edges_or_order(self):
  import copy
  p=pathlib.Path('dist/设备测试画布/项目/test1/Case 001.case.json')
  if not p.exists():self.skipTest('user case unavailable')
  w=self.w;data=load_case(p);w.nodes=copy.deepcopy(data['nodes']);w.edges=copy.deepcopy(data['edges']);before=copy.deepcopy(w.edges);order=[n['id'] for n in execution_order({'nodes':w.nodes,'edges':w.edges})]
  w.fit_canvas();w.update();self.assertEqual(w.edges,before);self.assertEqual([n['id'] for n in execution_order({'nodes':w.nodes,'edges':w.edges})],order)
  placed=[next(n for n in w.nodes if n['id']==k) for k in order]
  self.assertEqual(len({(n['x'],n['y']) for n in placed}),len(placed));self.assertEqual([n['y'] for n in placed],sorted(n['y'] for n in placed))
  for y in {n['y'] for n in placed}:
   xs=[n['x'] for n in placed if n['y']==y];self.assertEqual(xs,sorted(xs));self.assertTrue(all(b-a==220 for a,b in zip(xs,xs[1:])))
  self.assertEqual(load_case(w.case)['edges'],before)
 def test_layout_handles_disconnected_chains_and_rejects_cycles(self):
  from case_model import layout_order
  nodes=[{'id':'a','x':400,'y':0},{'id':'b','x':0,'y':300},{'id':'c','x':0,'y':0}]
  ordered=layout_order({'nodes':nodes,'edges':[{'from':'a','to':'b'}]})
  ids=[n['id'] for n in ordered];self.assertEqual(set(ids),{'a','b','c'});self.assertEqual(ids.index('b'),ids.index('a')+1)
  with self.assertRaisesRegex(ValueError,'循环'):
   layout_order({'nodes':nodes,'edges':[{'from':'a','to':'b'},{'from':'b','to':'a'}]})
 def test_multiple_captures_have_inline_previews(self):
  from PIL import Image
  w=self.w;w.add('wait',10,10);w.update();paths=[]
  for i in (1,2):
   img=w.project/f'{i}.png';Image.new('RGB',(100,50),'red' if i==1 else 'blue').save(img);paths.append(img)
   w.render_event({'event':'step_start','index':i,'total':2,'type':'capture','params':{'output':'x'}})
   w.render_event({'event':'step_done','index':i,'type':'capture','elapsed':.2,'message':'ok','artifacts':{'preview':str(img)}})
  w.update();self.assertFalse(w.steps.rows['1']['expanded']);self.assertFalse(w.steps.rows['2']['expanded']);self.assertEqual(len(w.log_windows),2)
  w.steps.toggle_image('1');w.update();self.assertTrue(w.steps.rows['1']['expanded']);self.assertIsNotNone(w.steps.rows['1']['photo']);self.assertFalse(w.steps.rows['2']['expanded'])
  w.steps.toggle_image('1');self.assertFalse(w.steps.rows['1']['expanded']);w.log_windows[1][1].invoke();w.update();self.assertTrue(w.log_windows[1][3]['expanded']);w.log_windows[1][1].invoke();self.assertFalse(w.log_windows[1][3]['expanded'])
  opened=[];old=w.show_large_image;w.show_large_image=lambda p:opened.append(str(p))
  try:w.open_step_preview('1');w.open_step_preview('2')
  finally:w.show_large_image=old
  self.assertEqual(opened,[str(x) for x in paths])
 def test_case_copy_paste_shortcuts(self):
  w=self.w;w.add('wait',15,15);original=w.case;w.tree.selection_set(str(original));w.tree.focus_force();w.update()
  w.tree.event_generate('<Control-KeyPress-c>');w.update();w.tree.event_generate('<Control-KeyPress-v>');w.update()
  self.assertNotEqual(w.case,original);self.assertTrue(w.case.exists());self.assertEqual(load_case(w.case),load_case(original))
 def test_overview_prepopulates_and_marks_unexecuted_after_failure(self):
  import time
  w=self.w;w.add('wait',20,20);w.add('wait',240,20);w.edges=[{'from':w.nodes[0]['id'],'to':w.nodes[1]['id']}]
  events=[{'event':'step_start','index':1,'total':2,'type':'wait','params':{'seconds':1}},{'event':'step_error','index':1,'type':'wait','message':'测试错误'}]
  class FakeProcess:
   def __init__(self,args,**kw):self.stdout=iter(['@@CANVAS_EVENT@@'+json.dumps(e,ensure_ascii=False)+'\n' for e in events])
   def wait(self):return 1
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   w.run_real();deadline=time.monotonic()+3
   while w.process and time.monotonic()<deadline:w.update();time.sleep(.02)
   self.assertEqual(w.steps.item('1','values')[2],'失败');self.assertEqual(w.steps.item('2','values')[2],'未执行');self.assertEqual(w.node_status[w.nodes[0]['id']],'error');self.assertEqual(w.node_status[w.nodes[1]['id']],'skipped');self.assertTrue(w.canvas.find_withtag('status:error'));self.assertTrue(w.canvas.find_withtag('status:skipped'))
  finally:app.subprocess.Popen=old
 def test_overview_and_inline_capture_preview(self):
  from PIL import Image
  w=self.w;w.add('wait',10,10);w.update();image=w.project/'sample.png';Image.new('RGB',(80,60),'red').save(image)
  w.render_event({'event':'step_start','index':1,'total':2,'type':'i2c_read','params':{'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':32,'expected':''}})
  w.render_event({'event':'step_done','index':1,'type':'i2c_read','elapsed':.1,'message':'[r] 0x00cc 0x12345678'})
  w.render_event({'event':'step_start','index':2,'total':2,'type':'capture','params':{'output':'x'}})
  w.render_event({'event':'step_done','index':2,'type':'capture','elapsed':.2,'message':'ok','artifacts':{'preview':str(image)}});w.update()
  self.assertEqual(w.steps.item('1','values')[2],'完成');self.assertIn('0x12345678',w.steps.item('1','values')[3]);self.assertEqual(w.steps.item('2','values')[2],'完成')
  self.assertFalse(w.steps.rows['2']['expanded']);self.assertIsNone(w.steps.rows['2']['photo']);w.steps.toggle_image('2');w.update();self.assertIsNotNone(w.steps.rows['2']['photo']);self.assertEqual(w.last_preview,image)
 def test_canvas_tracks_node_status_and_read_result(self):
  w=self.w;w.add('i2c_read',50,50);w.run_case_path=w.case;key=w.nodes[0]['id'];w.run_node_ids={1:key};w.node_status={key:'pending'};w.draw()
  p={'slave':'0x40','register':'0x00cc','address_bits':16,'data_bits':32,'expected':''}
  w.render_event({'event':'step_start','index':1,'total':1,'type':'i2c_read','params':p});w.update()
  self.assertEqual(w.node_status[key],'running');self.assertTrue(w.canvas.find_withtag('status:running'))
  w.render_event({'event':'step_done','index':1,'type':'i2c_read','elapsed':.1,'message':'[r] 0x00cc 0x0011bffc'});w.update()
  self.assertEqual(w.node_status[key],'success');self.assertEqual(w.node_results[key],'[r] 0x00cc 0x0011bffc');self.assertTrue(w.canvas.find_withtag('status:success'));self.assertTrue(w.canvas.find_withtag('run-result'))
  w.render_event({'event':'step_error','index':1,'type':'i2c_read','message':'失败'});self.assertEqual(w.node_status[key],'error');self.assertTrue(w.canvas.find_withtag('status:error'))
 def test_canvas_updates_while_background_run_is_active(self):
  import time,threading
  w=self.w;w.add('wait',20,20);nodeid=w.nodes[0]['id'];gate=threading.Event()
  start={'event':'step_start','index':1,'total':1,'type':'wait','params':{'seconds':1}}
  done={'event':'step_done','index':1,'type':'wait','elapsed':1.0,'message':'等待完成'}
  class FakeProcess:
   def __init__(self,args,**kw):
    def stream():
     yield '@@CANVAS_EVENT@@'+json.dumps(start,ensure_ascii=False)+'\n'
     gate.wait(3)
     yield '@@CANVAS_EVENT@@'+json.dumps(done,ensure_ascii=False)+'\n'
    self.stdout=stream()
   def wait(self):return 0
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   w.run_real();deadline=time.monotonic()+3
   while w.node_status.get(nodeid)!='running' and time.monotonic()<deadline:w.update();time.sleep(.02)
   self.assertIsNotNone(w.process);self.assertEqual(w.node_status[nodeid],'running');self.assertTrue(w.canvas.find_withtag('status:running'))
   gate.set();deadline=time.monotonic()+3
   while w.process and time.monotonic()<deadline:w.update();time.sleep(.02)
   self.assertIsNone(w.process);self.assertEqual(w.node_status[nodeid],'success');self.assertTrue(w.canvas.find_withtag('status:success'))
  finally:gate.set();app.subprocess.Popen=old
 def test_canvas_progress_is_scoped_to_running_case(self):
  w=self.w;w.add('wait',30,30);first=w.case;key=w.nodes[0]['id'];w.run_case_path=first;w.run_node_ids={1:key};w.node_status={key:'running'};w.draw()
  self.assertTrue(w.canvas.find_withtag('status:running'))
  w.case=w.project/'different.case.json';w.draw();self.assertFalse(w.canvas.find_withtag('status:running'))
  w.case=first;w.draw();self.assertTrue(w.canvas.find_withtag('status:running'))
 def test_nonfatal_i2c_failure_continues_and_returns_failure(self):
  import contextlib,io,hardware_runner as runner
  p=pathlib.Path(self.temp.name)/'flow.case.json';ini=self.w.project/'init.ini';ini.write_text('test',encoding='utf8')
  specs=[('power_on',{'ini':str(ini)}),('i2c_read',{'slave':'0x40','register':'0xcc','address_bits':16,'data_bits':32,'expected':'0x33','mask':'0xffffffff'}),('wait',{'seconds':0}),('capture',{'output':str(self.w.project/'image')}),('power_off',{}),('relay_off',{'port':'COM3','channel':0})]
  nodes=[{'id':str(i),'x':i,'y':0,'type':t,'params':v} for i,(t,v) in enumerate(specs)];p.write_text(json.dumps({'version':2,'nodes':nodes,'edges':[{'from':str(i),'to':str(i+1)} for i in range(len(nodes)-1)]}),encoding='utf8')
  calls=[]
  class Fake:
   def run(self,n):
    calls.append(n['type'])
    if n['type']=='i2c_read':raise RuntimeError('断言失败')
    return 'ok'
   def close(self):calls.append('close')
  old=runner.Hardware;runner.Hardware=Fake;out=io.StringIO()
  try:
   with contextlib.redirect_stdout(out):result=runner.main(p)
  finally:runner.Hardware=old
  self.assertEqual(result,2);self.assertEqual(calls,[x[0] for x in specs]+['close'])
  events=[json.loads(line[len('@@CANVAS_EVENT@@'):]) for line in out.getvalue().splitlines() if line.startswith('@@CANVAS_EVENT@@')]
  error=next(e for e in events if e['event']=='step_error');self.assertTrue(error['continued']);self.assertEqual(events[-1]['failed_count'],1)
 def test_critical_failure_stops_following_steps(self):
  import contextlib,io,hardware_runner as runner
  p=pathlib.Path(self.temp.name)/'flow.case.json';ini=self.w.project/'init.ini';ini.write_text('test',encoding='utf8')
  specs=[('power_on',{'ini':str(ini)}),('capture',{'output':'capture'}),('power_off',{})]
  nodes=[{'id':str(i),'x':i,'y':0,'type':t,'params':v} for i,(t,v) in enumerate(specs)];p.write_text(json.dumps({'version':2,'nodes':nodes,'edges':[{'from':str(i),'to':str(i+1)} for i in range(len(nodes)-1)]}),encoding='utf8')
  calls=[]
  class Fake:
   def run(self,n):calls.append(n['type']);raise RuntimeError('上电失败')
   def close(self):calls.append('close')
  old=runner.Hardware;runner.Hardware=Fake
  try:
   with contextlib.redirect_stdout(io.StringIO()):
    with self.assertRaisesRegex(RuntimeError,'上电失败'):runner.main(p)
  finally:runner.Hardware=old
  self.assertEqual(calls,['power_on','close'])
 def test_click_capture_row_expands_and_collapses(self):
  from PIL import Image
  w=self.w;w.add('wait',20,20);image=w.project/'capture.png';Image.new('RGB',(80,40),'red').save(image);w.update()
  w.render_event({'event':'step_start','index':1,'total':1,'type':'capture','params':{'output':'x'}})
  w.render_event({'event':'step_done','index':1,'type':'capture','message':'ok','elapsed':.1,'artifacts':{'preview':str(image)}});w.update()
  label=w.steps.rows['1']['labels'][0];label.event_generate('<Button-1>',x=4,y=4);w.update();self.assertTrue(w.steps.rows['1']['expanded'])
  label.event_generate('<Button-1>',x=4,y=4);w.update();self.assertFalse(w.steps.rows['1']['expanded'])
 def test_canvas_hover_preview_can_open_original(self):
  from PIL import Image
  w=self.w;w.add('capture',40,40);w.update();key=w.nodes[0]['id'];image=w.project/'capture.png';Image.new('RGB',(80,40),'red').save(image)
  w.run_case_path=w.case;w.node_artifacts[key]=str(image);w.hover_key=key;w.show_hover(key,100,100);w.update();self.assertIsNotNone(w.hover_window);self.assertIsNotNone(w.hover_photo)
  opened=[];old=w.show_large_image;w.show_large_image=lambda p:opened.append(str(p))
  try:
   frame=w.hover_window.winfo_children()[0];button=next(x for x in frame.winfo_children() if isinstance(x,app.ttk.Button));button.invoke()
  finally:w.show_large_image=old;w.hide_hover()
  self.assertEqual(opened,[str(image)])
 def test_soft_failure_summary_and_history_replay_keeps_current_parameters(self):
  import time
  from run_history import list_runs
  w=self.w;w.add('wait',20,20);w.add('wait',240,20);w.edges=[{'from':w.nodes[0]['id'],'to':w.nodes[1]['id']}]
  events=[{'event':'step_start','index':1,'total':2,'type':'wait','params':{'seconds':1}},{'event':'step_error','index':1,'type':'wait','message':'断言失败','continued':True},{'event':'step_start','index':2,'total':2,'type':'wait','params':{'seconds':1}},{'event':'step_done','index':2,'type':'wait','message':'等待完成','elapsed':.1}]
  class FakeProcess:
   def __init__(self,args,**kw):self.stdout=iter(['@@CANVAS_EVENT@@'+json.dumps(e,ensure_ascii=False)+'\n' for e in events])
   def wait(self):return 2
  old=app.subprocess.Popen;app.subprocess.Popen=FakeProcess
  try:
   w.run_real();deadline=time.monotonic()+3
   while w.process and time.monotonic()<deadline:w.update();time.sleep(.02)
  finally:app.subprocess.Popen=old
  self.assertIsNone(w.process);self.assertIn('有失败',w.run_status.cget('text'));self.assertEqual(w.steps.item('1','values')[2],'失败');self.assertEqual(w.steps.item('2','values')[2],'完成')
  runs=list_runs(w.case);self.assertEqual(runs[0]['status'],'有失败');self.assertEqual(runs[0]['failed'],1);self.assertEqual(len(runs[0]['events']),4)
  w.nodes[0]['params']['seconds']=9;w.selected=None;w.persist();w.refresh_history();w.history_tree.selection_set('0');w.on_history_selected();w.update()
  self.assertEqual(w.nodes[0]['params']['seconds'],9);self.assertEqual(w.steps.item('1','values')[2],'失败');self.assertEqual(w.steps.item('2','values')[2],'完成');self.assertIn('历史',w.run_status.cget('text'))
 def test_old_raw_log_history_is_readable(self):
  from run_history import inspect_run
  p=pathlib.Path('dist/设备测试画布/项目/test1/测试结果/Case 001/20261116-033124-258c27')
  if not p.exists():self.skipTest('old run unavailable')
  result=inspect_run(p);self.assertEqual(result['status'],'失败');self.assertGreater(len(result['events']),0);self.assertTrue(any(e['event']=='step_error' for e in result['events']))
 def test_image_enlarges_inside_application(self):
  from PIL import Image
  w=self.w;image=w.project/'large.png';Image.new('RGB',(80,50),'red').save(image);w.show_large_image(image);w.update()
  windows=[x for x in w.winfo_children() if isinstance(x,app.tk.Toplevel)];self.assertTrue(windows);self.assertIn('抓图查看',windows[-1].title())
  label=next(x for x in windows[-1].winfo_children() if isinstance(x,app.tk.Label));self.assertTrue(hasattr(label,'photo'));windows[-1].destroy()
 def test_hover_event_shows_and_hides_capture_popover(self):
  from PIL import Image
  import time,types
  w=self.w;w.add('capture',40,40);w.update();key=w.nodes[0]['id'];image=w.project/'capture.png';Image.new('RGB',(80,40),'red').save(image)
  w.preview_case_path=w.case;w.node_artifacts[key]=str(image);cv=w.canvas
  x=round(80*w.zoom-cv.canvasx(0));y=round(60*w.zoom-cv.canvasy(0));w.canvas_hover(types.SimpleNamespace(x=x,y=y,x_root=100,y_root=100))
  deadline=time.monotonic()+1
  while w.hover_window is None and time.monotonic()<deadline:w.update();time.sleep(.02)
  self.assertIsNotNone(w.hover_window);w.schedule_hover_hide();deadline=time.monotonic()+1
  while w.hover_window is not None and time.monotonic()<deadline:w.update();time.sleep(.02)
  self.assertIsNone(w.hover_window)
 def test_prior_failed_run_replays_old_snapshot_without_overwriting_case(self):
  import shutil
  source=pathlib.Path('dist/设备测试画布/项目/test1/测试结果/Case 001/20261116-033124-258c27')
  if not source.exists():self.skipTest('old run unavailable')
  w=self.w;w.add('wait',20,20);w.param_vars['seconds'].set('0.07');w.apply();w.persist();before=w.case.read_bytes()
  dest=w.case.parent/'测试结果'/w.case.name.removesuffix('.case.json')/source.name;dest.parent.mkdir(parents=True);shutil.copytree(source,dest)
  w.refresh_history();self.assertEqual(len(w.history_tree.get_children()),1);w.history_tree.selection_set('0');w.on_history_selected();w.update()
  self.assertEqual(w.case.read_bytes(),before);self.assertEqual(w.nodes[0]['params']['seconds'],0.07);self.assertEqual(w.steps.item('9','values')[2],'失败');self.assertEqual(w.steps.item('10','values')[2],'未执行');self.assertIn('历史',w.run_status.cget('text'))
 def test_historical_capture_is_available_for_canvas_hover(self):
  from PIL import Image
  w=self.w;w.add('capture',20,20);nodeid=w.nodes[0]['id'];w.persist();image=w.project/'history.png';Image.new('RGB',(50,30),'blue').save(image)
  run=w.project/'测试结果'/w.case.name.removesuffix('.case.json')/'20261116-010101-abc';(run/'配置').mkdir(parents=True);(run/'日志').mkdir()
  (run/'配置'/'执行快照.json').write_bytes(w.case.read_bytes());events=[{'event':'step_start','index':1,'total':1,'type':'capture','params':{'output':'x'}},{'event':'step_done','index':1,'type':'capture','elapsed':.1,'message':'ok','artifacts':{'preview':str(image)}}]
  (run/'日志'/'步骤事件.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf8');(run/'运行摘要.json').write_text(json.dumps({'status':'通过','exit_code':0,'failed_count':0}),encoding='utf8')
  w.refresh_history();w.history_tree.selection_set('0');w.on_history_selected();w.update();self.assertEqual(w.node_artifacts[nodeid],str(image));self.assertEqual(w.preview_case_path,w.case);self.assertIsNone(w.run_case_path)
  w.hover_key=nodeid;w.show_hover(nodeid,100,100);w.update();self.assertIsNotNone(w.hover_window);w.hide_hover()
 def test_user_case_runs_in_order_with_mock_hardware(self):
  import hardware_runner as runner
  p=pathlib.Path('dist/设备测试画布/项目/test1/Case 001.case.json')
  if not p.exists():self.skipTest('user case unavailable')
  calls=[]
  class FakeHardware:
   def run(self,node):calls.append(node['type']);return 'ok'
   def close(self):calls.append('close')
  previous=runner.Hardware;runner.Hardware=FakeHardware
  try: runner.main(p)
  finally: runner.Hardware=previous
  self.assertEqual(calls,[node['type'] for node in execution_order(load_case(p))]+['close'])
 def test_preflight_blocks_invalid_parameter_before_hardware(self):
  import hardware_runner as runner
  p=pathlib.Path(self.temp.name)/'invalid.case.json'
  p.write_text(json.dumps({'version':2,'nodes':[{'id':'a','x':0,'y':0,'type':'i2c_read','params':{'slave':'0x40','register':'0xcc','address_bits':16,'data_bits':16}}],'edges':[]}),encoding='utf-8')
  previous=runner.Hardware;runner.Hardware=lambda: self.fail('hardware initialized before validation')
  try:
   with self.assertRaises(ValueError):runner.main(p)
  finally:runner.Hardware=previous
 def test_validation_uses_unapplied_editor(self):
  w=self.w;w.add('wait',50,50);w.param_vars['seconds'].set('2');w.simulate();self.assertEqual(w.nodes[0]['params']['seconds'],2)

if __name__=='__main__':unittest.main(verbosity=2)
