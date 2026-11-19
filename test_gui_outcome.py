import os,sys,pathlib,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import app
class GuiTest(unittest.TestCase):
 def test_completion_warning_and_continue_error_visible(self):
  with tempfile.TemporaryDirectory() as t:
   w=app.App()
   try:
    w.project=pathlib.Path(t);w.folder=w.project;w.refresh();w.update();w.new_case();w.add('wait',20,20);w.update()
    node=w.nodes[0]['id'];w.run_node_ids={1:node}
    w.render_event({'event':'step_start','index':1,'total':1,'type':'firmware','params':{'ini':'a','firmware':'b'}})
    msg='进度已达100%，按测试要求视为完成；SDK状态 3、错误码 -13、接口返回 3；写入及校验结果未确认'
    w.render_event({'event':'step_done','index':1,'type':'firmware','message':msg,'elapsed':1,'sdk_status':3,'sdk_error':-13,'sdk_return':3,'verification':'未确认'})
    self.assertEqual(w.node_status[node],'success'); self.assertIn('-13',w.log.get('1.0','end'));self.assertIn('未确认',w.log.get('1.0','end'))
    w.render_event({'event':'step_error','index':1,'type':'firmware','message':'failed','continued':True});self.assertIn('继续执行后续步骤',w.log.get('1.0','end'));self.assertEqual(w.node_status[node],'error')
   finally:w.destroy()
if __name__=='__main__': unittest.main(verbosity=2)
