import json, math, os, pathlib, re, tkinter as tk
import queue, subprocess, sys, threading, uuid, datetime, copy
from case_model import load_case, execution_order, resolve_paths, validate_steps, layout_order
from run_history import list_batches
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk

if getattr(sys,'frozen',False):
    _exe_dir=pathlib.Path(sys.executable).resolve().parent
    ROOT=_exe_dir.parent if _exe_dir.name=='商务版' else _exe_dir
else:ROOT=pathlib.Path(__file__).resolve().parent
TYPES = {
    'wait': ('等待', {'seconds': 1.0}),
    'relay_on': ('继电器开', {'port': 'COM3', 'channel': 0}),
    'relay_off': ('继电器关', {'port': 'COM3', 'channel': 0}),
    'power_on': ('设备上电 / 初始化', {'ini': '${APPDIR}/assets/device.ini'}),
    'power_off': ('设备下电 / 关闭', {}),
    'i2c_read': ('I²C 读 / 断言', {'slave': '0x40', 'register': '0x00d8', 'address_bits': 16, 'data_bits': 32, 'expected': '', 'mask': '0xffffffff'}),
    'i2c_write': ('I²C 写', {'slave': '0x40', 'register': '0x0000', 'value': '0x00', 'address_bits': 16, 'data_bits': 8}),
    'firmware': ('固件下载', {'ini': '${APPDIR}/assets/device.ini', 'firmware': '${APPDIR}/assets/firmware.bin'}),
    'capture': ('抓图', {'output': '${RUNDIR}/图片/capture'}),
    'metrics': ('帧率 / DN / 断言', {'fps_min': '', 'fps_max': '', 'dn_min': '', 'dn_max': ''}),
    'firmware_backup': ('备份设备固件', {'ini': '${APPDIR}/assets/device.ini', 'address': '0x0', 'length': '0x76000', 'output': '${CASEDIR}/固件备份.bin'}),
    'binary_patch': ('生成修改后的固件副本', {'source': '${APPDIR}/assets/firmware.bin', 'output': '${CASEDIR}/输出/firmware_modified.bin', 'offset':'0x0', 'hex_bytes':'00'}),
}

class StepList(ttk.Frame):
    """Scrollable step rows; capture thumbnails are children of their own row."""
    def __init__(self,parent):
        super().__init__(parent);self.rows={};self.order=[];self.selected=None
        self.canvas=tk.Canvas(self,bg='#ffffff',highlightthickness=0)
        bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview);self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.inner=tk.Frame(self.canvas,bg='#ffffff');self.window=self.canvas.create_window(0,0,window=self.inner,anchor='nw')
        self.inner.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',self.resize_rows)
        self.canvas.bind('<MouseWheel>',lambda e:self.scroll(e))
    def resize_rows(self,event):
        self.canvas.itemconfigure(self.window,width=event.width)
        for row in self.rows.values():self.wrap_row(row)
    def wrap_row(self,row):
        available=max(90,self.canvas.winfo_width()-285-(80 if row.get('toggle') else 0))
        row['labels'][3].configure(wraplength=available,justify='left')
        if row.get('detail'):row['detail'].configure(wraplength=max(120,self.canvas.winfo_width()-36))
    def scroll(self,event):self.canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
    def get_children(self):return tuple(self.order)
    def exists(self,iid):return iid in self.rows
    def selection(self):return (self.selected,) if self.selected else ()
    def choose(self,iid):
        self.selected=iid;self.event_generate('<<TreeviewSelect>>')
        if iid in self.rows:
            row=self.rows[iid]
            if row.get('path'):self.toggle_image(iid)
            elif row.get('detail_toggle'):self.toggle_detail(iid)
    def insert(self,parent,index,iid,values,tags=()):
        card=tk.Frame(self.inner,bg='#ffffff',highlightthickness=1,highlightbackground='#e6ebf2');card.pack(fill='x',padx=5,pady=(4,0))
        head=tk.Frame(card,bg='#ffffff');head.pack(fill='x',padx=8,pady=5);head.columnconfigure(3,weight=1)
        labels=[]
        for col,(value,width) in enumerate(zip(values,(3,16,6,1))):
            label=tk.Label(head,text=str(value),bg='#ffffff',fg='#304057',anchor='w',font=('Microsoft YaHei UI',9),width=width if col!=3 else 1)
            label.grid(row=0,column=col,sticky='ew',padx=(0,6));labels.append(label)
        self.rows[iid]={'card':card,'head':head,'labels':labels,'values':tuple(values),'thumbnail':None,'photo':None,'toggle':None,'path':None,'expanded':False,'callback':None,'detail':None,'detail_toggle':None,'detail_expanded':False};self.order.append(iid)
        for widget in (card,head,*labels):
            widget.bind('<Button-1>',lambda e,k=iid:self.choose(k));widget.bind('<MouseWheel>',self.scroll)
        self.wrap_row(self.rows[iid]);self.item(iid,values=values,tags=tags);return iid
    def item(self,iid,option=None,**kw):
        row=self.rows[iid]
        if 'values' in kw:
            row['values']=tuple(str(x) for x in kw['values'])
            for label,value in zip(row['labels'][:3],row['values'][:3]):label.configure(text=value)
            message=row['values'][3] if len(row['values'])>3 else ''
            long=len(message)>24 or '\n' in message
            row['labels'][3].configure(text=(message[:16]+'…') if long else message)
            if long:
                if row['detail_toggle'] is None:
                    row['detail_toggle']=tk.Button(row['head'],text='展开详情 ▾',bg='#ffffff',fg='#2457a5',activebackground='#edf4ff',relief='flat',bd=0,cursor='hand2',font=('Microsoft YaHei UI',9),command=lambda k=iid:self.toggle_detail(k))
                    row['detail_toggle'].grid(row=0,column=4,sticky='e',padx=(3,0))
                if row['detail'] is None:
                    row['detail']=tk.Label(row['card'],bg='#f5f7fb',fg='#304057',anchor='w',justify='left',font=('Microsoft YaHei UI',9),padx=8,pady=6)
                    row['detail'].bind('<MouseWheel>',self.scroll)
                row['detail'].configure(text=message);self.wrap_row(row)
            else:
                if row['detail_toggle']:row['detail_toggle'].destroy();row['detail_toggle']=None
                if row['detail']:row['detail'].pack_forget();row['detail_expanded']=False
        if 'tags' in kw:
            tags=kw['tags'];color='#168052' if 'ok' in tags else '#c33838' if 'error' in tags else '#a86508' if 'running' in tags else '#667991'
            row['labels'][2].configure(fg=color)
        if option=='values':return row['values']
        return {'values':row['values']}
    def toggle_detail(self,iid):
        row=self.rows.get(iid)
        if not row or not row['detail_toggle']:return
        if row['detail_expanded']:
            row['detail'].pack_forget();row['detail_expanded']=False;row['detail_toggle'].configure(text='展开详情 ▾')
        else:
            row['detail'].pack(fill='x',padx=8,pady=(0,7));row['detail_expanded']=True;row['detail_toggle'].configure(text='收起详情 ▴')
        self.update_idletasks();self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    def attach_image(self,iid,path,callback):
        if iid not in self.rows:return False
        row=self.rows[iid];row['path']=path;row['callback']=callback
        for widget in (row['card'],row['head'],*row['labels']):widget.configure(cursor='hand2')
        if row['toggle'] is None:
            row['toggle']=tk.Button(row['head'],text='展开图片 ▾',bg='#ffffff',fg='#2457a5',activebackground='#edf4ff',relief='flat',bd=0,cursor='hand2',font=('Microsoft YaHei UI',9),command=lambda k=iid:self.toggle_image(k))
            row['toggle'].grid(row=0,column=4,sticky='e',padx=(3,0));self.wrap_row(row)
        return True
    def toggle_image(self,iid):
        if iid not in self.rows:return
        row=self.rows[iid]
        if row['expanded']:
            row['thumbnail'].pack_forget();row['expanded']=False;row['toggle'].configure(text='展开图片 ▾')
        else:
            try:
                with Image.open(row['path']) as source:
                    image=source.copy();image.thumbnail((360,150),Image.Resampling.LANCZOS)
                photo=ImageTk.PhotoImage(image,master=self)
            except (OSError,ValueError,tk.TclError) as e:
                messagebox.showerror('无法预览',str(e));return
            if row['thumbnail'] is None:
                row['thumbnail']=tk.Label(row['card'],bg='#f5f7fb',cursor='hand2',anchor='w');row['thumbnail'].bind('<MouseWheel>',self.scroll)
            row['photo']=photo;row['thumbnail'].configure(image=photo);row['thumbnail'].bind('<Button-1>',lambda e:row['callback']())
            row['thumbnail'].pack(fill='x',padx=8,pady=(0,7));row['expanded']=True;row['toggle'].configure(text='收起图片 ▴')
        self.update_idletasks();self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    def delete(self,*ids):
        for iid in ids:
            if iid in self.rows:self.rows.pop(iid)['card'].destroy();self.order.remove(iid)
            if self.selected==iid:self.selected=None
    def see(self,iid):
        if iid not in self.rows:return
        self.update_idletasks();height=self.inner.winfo_height();viewport=self.canvas.winfo_height()
        if height<=viewport:return
        y=self.rows[iid]['card'].winfo_y();self.canvas.yview_moveto(max(0,min(1,(y-viewport*.35)/height)))

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('自动化测试工作台'); self.geometry('1600x900'); self.configure(bg='#f3f5f9')
        self._history_refreshing=False;self.batch=None;self.repeat_var=tk.StringVar(value='1');self.repeat_count=1;self.project = ROOT / '项目'; self.project.mkdir(parents=True,exist_ok=True); self.folder = self.project; self.case = None; self.nodes = []; self.edges = []; self.linking = None; self.selected = None; self.selected_edge = None; self.node_clipboard = None; self.case_clipboard = None; self.step_rows = {}; self.step_artifacts = {}; self.log_images = []; self.log_windows = []; self.run_node_ids = {}; self.node_status = {}; self.node_results = {}; self.node_artifacts = {}; self.preview_case_path = None; self.hover_window = None; self.hover_photo = None; self.hover_key = None; self.hover_timer = None; self.hide_timer = None; self.run_case_path = None; self.preview_image = None; self.preview_path = None; self.preview_source = None; self.simulating = False; self.zoom = 1.0; self.drag = None; self.process = None; self.runlog = None; self.readable_log = None; self.current_run_dir = None; self.last_image_dir = None; self.last_preview = None; self.step_failed = False; self.run_failures = []; self.event_file = None; self.run_summary = None; self.history_items = {}; self.history_snapshot_path = None; self.replaying = False; self.messages = queue.Queue(); self.protocol('WM_DELETE_WINDOW',self.close_window);self.bind('<Destroy>',self.cleanup_hover,add='+')
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('.', background='#f3f5f9', foreground='#26354c', fieldbackground='#ffffff',font=('Microsoft YaHei UI',9))
        style.configure('TButton', padding=(10,6),background='#ffffff',foreground='#34435b',bordercolor='#d7dfeb',lightcolor='#ffffff',darkcolor='#e4e9f0');style.map('TButton',background=[('active','#eaf1fd')])
        style.configure('Primary.TButton',background='#2563eb',foreground='#ffffff',bordercolor='#2563eb');style.map('Primary.TButton',background=[('active','#1d4ed8')],foreground=[('active','#ffffff')])
        style.configure('Treeview',rowheight=27,background='#ffffff',fieldbackground='#ffffff',foreground='#304057',bordercolor='#e1e7f0');style.map('Treeview',background=[('selected','#dceaff')],foreground=[('selected','#17457d')])
        style.configure('Treeview.Heading',background='#eef2f8',foreground='#53637a',font=('Microsoft YaHei UI',9,'bold'),relief='flat')
        style.configure('TNotebook',background='#f3f5f9',borderwidth=0);style.configure('TNotebook.Tab',padding=(12,6))
        top=ttk.Frame(self); top.pack(fill='x')
        ttk.Label(top,text='自动化测试  /  工作台',font=('Microsoft YaHei UI',13,'bold'),foreground='#183153').pack(side='left',padx=(16,20),pady=12)
        for label,command in [('新建项目',self.new_project),('打开项目',self.open_project),('新建 Case',self.new_case),('保存',self.save),('校验',self.validate),('模拟运行',self.simulate),('真实运行',self.run_real)]:
            ttk.Button(top,text=label,command=command,style='Primary.TButton' if label=='真实运行' else 'TButton').pack(side='left',padx=3,pady=6)
        ttk.Label(top,text='默认  COM3 / CHANNEL 0',foreground='#4c6b92').pack(side='right',padx=14)
        ttk.Label(top,text='重复次数').pack(side='left',padx=(10,2));self.repeat_entry=ttk.Spinbox(top,from_=1,to=10000,width=5,textvariable=self.repeat_var);self.repeat_entry.pack(side='left');self.repeat_entry.bind('<FocusOut>',self.repeat_changed)
        body=ttk.Panedwindow(self,orient='horizontal'); body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=220); body.add(left,weight=1)
        ttk.Label(left,text='项目与 CASE',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',padx=12,pady=(14,8))
        self.tree=ttk.Treeview(left,show='tree'); self.tree.pack(fill='both',expand=True,padx=6); self.tree.bind('<<TreeviewSelect>>',self.select_case); self.tree.bind('<Button-3>',self.tree_menu);self.tree.bind('<Control-c>',self.copy_case_key);self.tree.bind('<Control-v>',self.paste_case_key)
        ttk.Button(left,text='复制选中 Case',command=self.duplicate_case).pack(fill='x',padx=7,pady=8)
        ttk.Label(left,text='右键画布添加节点',foreground='#73849b').pack(anchor='w',padx=10,pady=(0,10))
        middle=ttk.Frame(body); body.add(middle,weight=5)
        zoom_bar=ttk.Frame(middle);zoom_bar.pack(fill='x')
        ttk.Button(zoom_bar,text='－',width=3,command=lambda:self.zoom_center(1/1.12)).pack(side='left',padx=2)
        self.zoom_label=ttk.Label(zoom_bar,text='100%');self.zoom_label.pack(side='left',padx=6)
        ttk.Button(zoom_bar,text='＋',width=3,command=lambda:self.zoom_center(1.12)).pack(side='left',padx=2)
        ttk.Button(zoom_bar,text='适应画布',command=self.fit_canvas).pack(side='left',padx=5)
        canvas_frame=ttk.Frame(middle); canvas_frame.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(canvas_frame,bg='#f5f7fb',highlightthickness=0,scrollregion=(-10000,-10000,10000,10000)); self.canvas.grid(row=0,column=0,sticky='nsew')
        canvas_frame.rowconfigure(0,weight=1); canvas_frame.columnconfigure(0,weight=1)
        self.bind('<Control-s>',lambda e:self.save()); self.canvas.bind('<Delete>',lambda e:self.delete_selection()); self.canvas.bind('<BackSpace>',lambda e:self.delete_selection()); self.canvas.bind('<Control-c>',lambda e:self.copy_node()); self.canvas.bind('<Control-v>',lambda e:self.paste_node()); self.canvas.bind('<Control-d>',lambda e:self.duplicate_node()); self.canvas.bind('<MouseWheel>',self.zoom_canvas); self.canvas.bind('<Button-1>',self.click); self.canvas.bind('<B1-Motion>',self.move); self.canvas.bind('<ButtonRelease-1>',self.release); self.canvas.bind('<Button-3>',self.context_menu); self.canvas.xview_moveto(.5); self.canvas.yview_moveto(.5)
        bottom=ttk.Frame(middle); bottom.pack(fill='x'); ttk.Label(bottom,text='左键拖动  ·  滚轮缩放  ·  圆点连线  ·  Ctrl+C / V  ·  右键菜单').pack(side='right',padx=8); self.status=ttk.Label(bottom,text='先打开一个项目目录，再新建 Case。'); self.status.pack(anchor='w',padx=10,pady=8)
        right=ttk.Frame(body,width=440); body.add(right,weight=3)
        ttk.Label(right,text='节点配置',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',padx=12,pady=(14,8))
        self.param_frame=ttk.Frame(right); self.param_frame.pack(fill='x',padx=8)
        self.param_vars={}; self.param_types={}
        ttk.Button(right,text='应用参数',command=self.apply).pack(fill='x',padx=8,pady=4)
        ttk.Button(right,text='删除节点',command=self.delete).pack(fill='x',padx=8,pady=4)
        logheader=ttk.Frame(right);logheader.pack(fill='x',padx=8,pady=(12,5))
        ttk.Label(logheader,text='运行结果',font=('Microsoft YaHei UI',10,'bold')).pack(side='left')
        self.run_status=ttk.Label(logheader,text='待运行',foreground='#65758d');self.run_status.pack(side='right')
        actions=ttk.Frame(right);actions.pack(fill='x',padx=8,pady=(0,5))
        for label,command in [('结果目录',self.open_run_dir),('图片目录',self.open_image_dir),('查看原图',self.open_preview),('完整日志',self.open_raw_log)]:
            ttk.Button(actions,text=label,command=command).pack(side='left',padx=(0,3))
        self.history_nav=ttk.Frame(right);self.history_back=ttk.Button(self.history_nav,text='← 返回执行记录',command=self.return_to_history);self.history_back.pack(side='left');ttk.Label(self.history_nav,text='正在查看历史结果',foreground='#65758d').pack(side='left',padx=10)
        tabs=ttk.Notebook(right);tabs.pack(fill='both',expand=True,padx=8,pady=(0,5));self.tabs=tabs
        overview=ttk.Frame(tabs);detail=ttk.Frame(tabs);history=ttk.Frame(tabs);self.overview_tab=overview
        tabs.add(overview,text='流程总览');tabs.add(detail,text='详细日志');tabs.add(history,text='执行记录');self.history_tab=history
        controls=ttk.Frame(history);controls.pack(fill='x',padx=4,pady=4)
        ttk.Label(controls,text='最新在前 · 展开批次选择轮次',foreground='#65758d').pack(side='left')
        ttk.Button(controls,text='查看参数快照',command=lambda:self.open_path(self.history_snapshot_path)).pack(side='right')
        self.history_tree=ttk.Treeview(history,columns=('time','status'),show='tree headings',selectmode='browse')
        self.history_tree.heading('#0',text='批次 / 轮次');self.history_tree.column('#0',width=140,minwidth=110,stretch=False)
        for col,title,width in [('time','启动时间',145),('status','执行结果',190)]:self.history_tree.heading(col,text=title);self.history_tree.column(col,width=width,anchor='w')
        history_bar=ttk.Scrollbar(history,orient='vertical',command=self.history_tree.yview);self.history_tree.configure(yscrollcommand=history_bar.set);history_bar.pack(side='right',fill='y');self.history_tree.pack(fill='both',expand=True)
        self.history_tree.bind('<<TreeviewSelect>>',self.on_history_selected);self.history_tree.bind('<Button-1>',self.history_click);self.history_tree.bind('<Double-Button-1>',self.history_click);tabs.bind('<<NotebookTabChanged>>',self.on_tab_change)
        self.steps=StepList(overview);self.steps.pack(fill='both',expand=True);self.steps.bind('<<TreeviewSelect>>',self.select_step)
        self.log=tk.Text(detail,width=45,height=12,bg='#ffffff',fg='#26354c',insertbackground='#26354c',state='disabled',wrap='word',font=('Microsoft YaHei UI',9),spacing1=1,spacing3=1,relief='flat',padx=10,pady=8)
        scrollbar=ttk.Scrollbar(detail,orient='vertical',command=self.log.yview);self.log.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');self.log.pack(side='left',fill='both',expand=True)
        self.log.tag_configure('heading',foreground='#2457a5',font=('Microsoft YaHei UI',9,'bold'),spacing1=5)
        self.log.tag_configure('success',foreground='#168052');self.log.tag_configure('error',foreground='#c33838',font=('Microsoft YaHei UI',9,'bold'))
        self.log.tag_configure('value',foreground='#9a5b05',font=('Microsoft YaHei UI',9,'bold'));self.log.tag_configure('muted',foreground='#728097');self.log.tag_configure('path',foreground='#2457a5')
        self.refresh();self.draw();self.say('项目目录：'+str(self.project))
    def on_tab_change(self,event=None):
        self.update_history_navigation()
    def update_history_navigation(self):
        if self.history_snapshot_path and self.tabs.select()!=str(self.history_tab):
            self.history_nav.pack(fill='x',padx=8,pady=(0,5),before=self.tabs)
        else:self.history_nav.pack_forget()
    def history_click(self,event):
        tree=self.history_tree;item=tree.identify_row(event.y)
        if not item:return
        if not tree.parent(item):
            tree.selection_set(item);tree.focus(item);tree.item(item,open=not tree.item(item,'open'));return 'break'
        if tree.selection()==(item,):
            self.on_history_selected();return 'break'
    def return_to_history(self):
        self.tabs.select(self.history_tab)
        selected=self.history_tree.selection()
        if selected:self.history_tree.see(selected[0])
    def refresh_history(self):
        if not hasattr(self,'history_tree'):return
        old_roots=self.history_tree.get_children();expanded={item for item in old_roots if self.history_tree.item(item,'open')}
        selected=self.history_tree.selection();position=self.history_tree.yview()[0]
        self._history_refreshing=True
        self.history_tree.delete(*old_roots);self.history_items={}
        if not self.case:self._history_refreshing=False;return
        try:batches=list_batches(self.case)
        except OSError as e:self._history_refreshing=False;self.say('读取执行记录失败：'+str(e));return
        for batch_number,batch in enumerate(batches):
            first=batch['runs'][0];name=first['directory'].name
            try:timestamp=datetime.datetime.strptime(name[:15],'%Y%m%d-%H%M%S').strftime('%m-%d %H:%M:%S')
            except ValueError:timestamp=name
            key='batch:'+batch['id'];parts=[f"通过 {batch['passed']}",f"失败 {batch['failed']}"]
            if batch['unknown']:
                active=self.batch and self.batch['id']==batch['id'] and self.process
                parts.append(f"{'运行中' if active else '未结束'} {batch['unknown']}")
            if batch['not_run']:parts.append(f"未执行 {batch['not_run']}")
            self.history_tree.insert('','end',iid=key,text=f"执行批次 · {batch['total']} 轮",values=(timestamp,'  '.join(parts)),open=key in expanded or (not old_roots and batch_number==0))
            for run in batch['runs']:
                child='run:'+str(run['directory']);self.history_items[child]=run
                round_status='运行中' if run['status']=='未结束' and self.batch and self.batch['id']==batch['id'] and self.process else run['status']
                try:round_time=datetime.datetime.strptime(run['directory'].name[:15],'%Y%m%d-%H%M%S').strftime('%m-%d %H:%M:%S')
                except ValueError:round_time=timestamp
                self.history_tree.insert(key,'end',iid=child,text=f"第 {run['repeat_index']} / {run['repeat_total']} 轮",values=(round_time,round_status+(f" · {run['failed']} 步失败" if run['failed'] else '')))
        if selected and self.history_tree.exists(selected[0]):self.history_tree.selection_set(selected[0])
        self.history_tree.yview_moveto(position)
        self.after_idle(lambda:setattr(self,'_history_refreshing',False))
    def on_history_selected(self,event=None):
        if event is not None and self._history_refreshing:return
        selected=self.history_tree.selection()
        if not selected:return
        if self.process:
            self.say('运行期间请等待结束后查看历史记录');return
        run=self.history_items.get(selected[0])
        if not run:return
        try:
            data=load_case(run['snapshot']);nodes=execution_order(data)
            self.clear_log();self.reset_overview();self.run_case_path=None;self.preview_case_path=self.case;self.run_node_ids={i:node['id'] for i,node in enumerate(nodes,1)};self.node_status={};self.node_results={};self.node_artifacts={};self.hide_hover();self.draw()
            self.current_run_dir=run['directory'];self.raw_log_path=run['raw'];self.history_snapshot_path=run['snapshot'];self.last_preview=None;self.last_image_dir=None;self.step_failed=False
            self.log_append('历史执行记录 · 当前 Case 参数不会改变','heading');self.log_append('执行目录：'+str(run['directory']),'path')
            self.simulating=True
            for i,node in enumerate(nodes,1):self.step_update({'event':'step_start','index':i,'total':len(nodes),'type':node['type'],'params':node['params']})
            self.simulating=False;self.replaying=True
            for item in run['events']:self.render_event(item)
            self.replaying=False
            for row in self.steps.get_children():
                values=list(self.steps.item(row,'values'))
                if values[2] in ('待执行','运行中'):
                    values[2]='未执行' if values[2]=='待执行' else '中断';self.steps.item(row,values=values,tags=('error',) if values[2]=='中断' else ())
            if not run['events'] and run['detail'].is_file():self.log_append(run['detail'].read_text(encoding='utf-8',errors='replace'),'muted')
            self.run_status.config(text=f"历史 · 第 {run['repeat_index']}/{run['repeat_total']} 轮 · {run['status']}",foreground='#65758d');self.log_append('\n历史结果：'+run['status'],'success' if run['status']=='通过' else 'error')
            self.tabs.select(self.overview_tab);self.update_history_navigation();self.say('正在查看历史执行记录；当前画布参数未改变')
        except (OSError,ValueError,KeyError,TypeError) as e:
            self.simulating=False;self.replaying=False;messagebox.showerror('无法读取历史记录',str(e))
    def reset_overview(self):
        self.steps.delete(*self.steps.get_children());self.step_rows={};self.step_artifacts={};self.log_images=[];self.log_windows=[]
    def select_step(self,event=None):
        selected=self.steps.selection()
        if not selected:return
        artifact=self.step_artifacts.get(selected[0],{})
        if artifact.get('preview'):
            self.last_preview=pathlib.Path(artifact['preview']);self.last_image_dir=self.last_preview.parent
    def open_step_preview(self,index):
        artifact=self.step_artifacts.get(str(index),{});path=artifact.get('preview')
        if path:self.last_preview=pathlib.Path(path);self.last_image_dir=self.last_preview.parent;self.show_large_image(path)
    def add_log_preview(self,path):
        container=tk.Frame(self.log,bg='#ffffff');preview=tk.Label(container,bg='#f5f7fb',cursor='hand2',anchor='w');state={'photo':None,'expanded':True}
        try:
            with Image.open(path) as source:
                image=source.copy();image.thumbnail((360,200),Image.Resampling.LANCZOS)
            state['photo']=ImageTk.PhotoImage(image,master=container);preview.configure(image=state['photo'])
        except (OSError,ValueError,tk.TclError):
            container.destroy();self.log_append('图片预览不可用，请检查文件路径','error');return
        preview.pack(anchor='w',pady=(3,5));preview.bind('<Button-1>',lambda e:self.show_large_image(path))
        def scroll_log(event):
            delta=event.delta;self.log.yview_scroll(-max(1,abs(delta)//120)*(1 if delta>0 else -1),'units');return 'break'
        for widget in (container,preview):widget.bind('<MouseWheel>',scroll_log)
        self.log_windows.append((container,None,preview,state));self.log.config(state='normal');self.log.window_create('end',window=container,padx=8,pady=2);self.log.insert('end','\n');self.log.see('end');self.log.config(state='disabled')
    def step_update(self,event):
        kind=event.get('event');idx=str(event.get('index',''));typ=event.get('type');p=event.get('params',{});label=TYPES.get(typ,(typ,))[0]
        if kind=='step_start':
            result=''
            if typ in ('i2c_read','i2c_write'):result=f"{p.get('slave','')} · {p.get('register','')}"
            elif typ=='wait':result=f"{p.get('seconds','')} 秒"
            elif typ in ('relay_on','relay_off'):result=f"{p.get('port','')} / CH{p.get('channel','')}"
            values=(idx,label,'待执行' if self.simulating else '运行中',result)
            if self.steps.exists(idx):self.steps.item(idx,values=values,tags=('running',) if not self.simulating else ())
            else:self.steps.insert('','end',iid=idx,values=values,tags=('running',) if not self.simulating else ())
            if not self.simulating:self.steps.see(idx)
        elif kind in ('step_done','step_error') and idx and self.steps.exists(idx):
            prior=self.steps.item(idx,'values');msg=event.get('message','')
            if typ=='capture' and kind=='step_done':
                artifacts=event.get('artifacts',{});self.step_artifacts[idx]=artifacts;msg='抓图完成 · 点击预览' if artifacts.get('preview') else '抓图完成'
            self.steps.item(idx,values=(prior[0],prior[1],'失败' if kind=='step_error' else '完成',msg),tags=('error' if kind=='step_error' else 'ok',))
            if typ=='capture' and kind=='step_done' and artifacts.get('preview'):
                self.steps.attach_image(idx,artifacts['preview'],lambda k=idx:self.open_step_preview(k))
            self.steps.see(idx)
    def cleanup_hover(self,event):
        if event.widget is self:self.hide_hover()
    def close_window(self):
        if self.process: return messagebox.showwarning("正在运行", "请等待当前 Case 完成后再关闭窗口。")
        if not self.commit_current():return
        self.destroy()
    def commit_current(self):
        if self.case:
            if self.selected is not None and not self.apply(): return False
            if not self.read_repeat_count():return False
            self.persist()
        return True
    def say(self,s):
        self.status.config(text=s)
    def log_append(self,text,tag=None):
        at_end=self.log.yview()[1]>.99;self.log.config(state='normal');self.log.insert('end',text+'\n',tag or ());
        if at_end:self.log.see('end')
        self.log.config(state='disabled')
        if self.readable_log:
            self.readable_log.write(text+'\n');self.readable_log.flush()
    def clear_log(self):
        self.log.config(state='normal');self.log.delete('1.0','end');self.log.config(state='disabled')
    def open_path(self,path):
        if not path or not pathlib.Path(path).exists():return messagebox.showinfo('暂无文件','当前还没有可打开的结果。')
        try:os.startfile(str(path))
        except OSError as e:messagebox.showerror('无法打开',str(e))
    def open_run_dir(self):self.open_path(self.current_run_dir)
    def open_image_dir(self):self.open_path(self.last_image_dir)
    def open_preview(self):
        if not self.last_preview:return messagebox.showinfo('暂无图片','当前还没有可打开的抓图。')
        self.show_large_image(self.last_preview)
    def show_large_image(self,path):
        self.hide_hover();self.open_path(path)
    def open_raw_log(self):self.open_path(self.raw_log_path if self.current_run_dir else None)
    def expand_log(self):
        window=tk.Toplevel(self);window.title('执行记录');window.geometry('1050x720')
        text=tk.Text(window,wrap='word',bg='#121720',fg='#e4eaf2',font=('Microsoft YaHei UI',11),padx=14,pady=12)
        bar=ttk.Scrollbar(window,orient='vertical',command=text.yview);text.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');text.pack(fill='both',expand=True)
        for tag in ('heading','success','error','value','muted','path'):text.tag_configure(tag,foreground={'heading':'#8ecbff','success':'#9ae6b4','error':'#ff9292','value':'#f7dc93','muted':'#9ba9ba','path':'#94caff'}[tag])
        timer={'id':None}
        def cancel_refresh(event):
            if event.widget is window and timer['id'] is not None:
                self.after_cancel(timer['id']);timer['id']=None
        window.bind('<Destroy>',cancel_refresh,add='+')
        def refresh_view():
            if not window.winfo_exists():return
            first,last=text.yview();at_end=last>.99
            text.config(state='normal');text.delete('1.0','end');text.insert('1.0',self.log.get('1.0','end-1c'))
            for tag in ('heading','success','error','value','muted','path'):
                spans=self.log.tag_ranges(tag)
                for i in range(0,len(spans),2):text.tag_add(tag,str(spans[i]),str(spans[i+1]))
            text.config(state='disabled')
            if at_end:text.see('end')
            else:text.yview_moveto(first)
            timer['id']=self.after(500,refresh_view)
        refresh_view()
    def open_project(self):
        if self.process:return messagebox.showwarning('正在运行','请等待运行结束后切换项目')
        if not self.commit_current():return
        p=filedialog.askdirectory(title='选择项目目录');
        if p: self.project=pathlib.Path(p).resolve(); self.folder=self.project; self.case=None; self.nodes=[]; self.edges=[]; self.selected=None; self.show_params(); self.refresh(); self.draw(); self.say('项目目录：'+p)
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        if not self.project:return
        folders={self.project:''}
        for root,dirs,files in os.walk(self.project):
            dirs[:]=sorted(name for name in dirs if name not in ('运行记录','测试结果'))
            parent=pathlib.Path(root)
            if parent not in folders:continue
            for name in dirs:
                folder=parent/name;key='dir:'+str(folder);self.tree.insert(folders[parent],'end',iid=key,text=name,open=True);folders[folder]=key
            for name in sorted(files):
                if name.endswith('.case.json'):
                    path=parent/name;self.tree.insert(folders[parent],'end',iid=str(path),text=name.removesuffix('.case.json'))
    def new_project(self):
        if self.process:return messagebox.showwarning('正在运行','请等待运行结束后新建项目')
        name=simpledialog.askstring('新建项目','项目名称：',parent=self)
        if not name:return
        name=name.strip()
        if not name or name in ('.','..') or any(ch in name for ch in '<>:"/\\|?*') or name.endswith(('.', ' ')):
            return messagebox.showerror('名称无效','请使用有效的文件夹名称')
        folder=self.project/name
        try: folder.mkdir(exist_ok=False)
        except OSError as e:return messagebox.showerror('无法创建项目',str(e))
        self.folder=folder; self.refresh(); self.tree.selection_set('dir:'+str(folder)); self.new_case()
    def tree_menu(self,event):
        item=self.tree.identify_row(event.y)
        if item:self.tree.selection_set(item)
        menu=tk.Menu(self,tearoff=False);menu.add_command(label='新建 Case',command=self.new_case)
        if item and not item.startswith('dir:'):
            menu.add_command(label='复制 Case',command=lambda:self.copy_case(item));menu.add_command(label='直接生成 Case 副本',command=lambda:self.duplicate_case(item))
        if self.case_clipboard:menu.add_command(label='粘贴 Case',command=self.paste_case)
        if item:menu.add_command(label='重命名',command=lambda:self.rename_tree_item(item))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
    def copy_case_key(self,event):self.copy_case();return 'break'
    def paste_case_key(self,event):self.paste_case();return 'break'
    def copy_case(self,item=None):
        if item is None:
            selected=self.tree.selection();item=selected[0] if selected else None
        if not item or item.startswith('dir:'):
            self.say('请先在左侧选择要复制的 Case');return False
        source=pathlib.Path(item)
        try:
            if source==self.case and not self.commit_current():return False
            self.case_clipboard=(source.name.removesuffix('.case.json'),source.read_bytes());self.say('Case 已复制，可在目标目录按 Ctrl+V');return True
        except OSError as e:messagebox.showerror('复制失败',str(e));return False
    def paste_case(self):
        if not self.case_clipboard:self.say('请先复制一个 Case');return
        if not self.commit_current():return
        selected=self.tree.selection();item=selected[0] if selected else None
        folder=pathlib.Path(item[4:]) if item and item.startswith('dir:') else pathlib.Path(item).parent if item else self.folder
        try:
            root=self.project.resolve()
            if not folder.resolve().is_relative_to(root):raise ValueError('目标目录不在当前项目中')
            name,data=self.case_clipboard;number=1
            while True:
                suffix=' - 副本' if number==1 else f' - 副本 {number}'
                target=folder/(name+suffix+'.case.json')
                try:
                    with target.open('xb') as f:f.write(data)
                    break
                except FileExistsError:number+=1
            self.folder=folder;self.refresh();self.tree.selection_set(str(target));self.tree.see(str(target));self.select_case();self.say('已创建副本：'+target.name)
        except (OSError,ValueError) as e:messagebox.showerror('粘贴失败',str(e))
    def duplicate_case(self,item=None):
        if self.copy_case(item):self.paste_case()
    def rename_tree_item(self,item):
        is_dir=item.startswith('dir:');old=pathlib.Path(item[4:] if is_dir else item)
        old_display=old.name if is_dir else old.name.removesuffix('.case.json')
        name=simpledialog.askstring('重命名','新名称：',initialvalue=old_display,parent=self)
        if not name:return
        name=name.strip()
        if not name or name in ('.','..') or any(ch in name for ch in '<>:"/\\|?*') or name.endswith(('.', ' ')):
            return messagebox.showerror('名称无效','请使用有效的名称')
        new=old.with_name(name if is_dir else name+'.case.json')
        if new==old:return
        if new.exists():return messagebox.showerror('无法重命名','目标名称已经存在')
        try:
            if self.selected is not None:
                if not self.apply():return
                self.persist()
            old.rename(new)
            if self.case:
                if self.case==old:self.case=new
                elif is_dir and self.case.is_relative_to(old):self.case=new/self.case.relative_to(old)
            if self.folder==old:self.folder=new
            elif is_dir and self.folder.is_relative_to(old):self.folder=new/self.folder.relative_to(old)
            self.refresh();self.tree.selection_set(('dir:' if is_dir else '')+str(new));self.say('已重命名：'+name)
        except OSError as e:messagebox.showerror('无法重命名',str(e))
    def new_case(self):
        if self.process:return messagebox.showwarning('正在运行','请等待运行结束后切换 Case')
        if not self.commit_current():return
        folder=self.folder if self.folder and self.folder.is_relative_to(self.project) else self.project
        folder.mkdir(parents=True,exist_ok=True)
        number=1
        while (folder/f'Case {number:03d}.case.json').exists(): number+=1
        self.case=folder/f'Case {number:03d}.case.json'; self.repeat_count=1;self.repeat_var.set('1'); self.nodes=[]; self.edges=[]; self.selected=None; self.show_params(); self.draw()
        if self.save():
            self.history_nav.pack_forget();self.history_snapshot_path=None;self.current_run_dir=None;self.last_preview=None;self.last_image_dir=None
            self.clear_log();self.reset_overview();self.run_case_path=None;self.preview_case_path=None;self.node_status={};self.node_results={};self.node_artifacts={};self.run_status.config(text='待运行',foreground='#65758d');self.draw();self.refresh_history()
            self.tree.selection_set(str(self.case)); self.say('已创建 '+str(self.case.relative_to(self.project)))
    def select_case(self,e=None):
        selected=self.tree.selection()
        if not selected:return
        if selected[0].startswith('dir:'):
            self.folder=pathlib.Path(selected[0][4:]); return
        try:
            p=pathlib.Path(selected[0])
            if self.case == p:return
            if self.process:
                self.tree.selection_set(str(self.case));self.say('请等待运行结束后切换 Case');return
            if not self.commit_current():return
            data=load_case(p)
            self.case=p; self.folder=p.parent; self.repeat_count=data.get('repeat_count',1);self.repeat_var.set(str(self.repeat_count)); self.nodes=data['nodes']; self.edges=data['edges']; self.linking=None; self.selected=None; self.selected_edge=None; self.show_params();self.clear_log();self.reset_overview();self.current_run_dir=None;self.last_preview=None;self.last_image_dir=None;self.history_snapshot_path=None;self.history_nav.pack_forget();self.run_case_path=None;self.preview_case_path=None;self.node_status={};self.node_results={};self.node_artifacts={};self.hide_hover();self.run_status.config(text='待运行',foreground='#65758d');self.draw();self.refresh_history();self.say('已打开 '+p.name)
        except Exception as ex: messagebox.showerror('打开失败',str(ex))
    def repeat_changed(self,event=None):
        try:value=int(self.repeat_var.get())
        except ValueError:return
        if 1<=value<=10000:self.repeat_count=value;self.persist()
    def read_repeat_count(self):
        try:
            value=int(self.repeat_var.get())
            if not 1<=value<=10000:raise ValueError()
        except ValueError:
            messagebox.showerror('重复次数无效','请输入 1 到 10000 之间的整数。');return False
        self.repeat_count=value;return True
    def save(self):
        if not self.case: messagebox.showwarning('提示','请先新建或选择 Case'); return False
        if self.selected is not None and not self.apply(): return False
        if not self.read_repeat_count():return False
        self.case.write_text(json.dumps({'version':2,'repeat_count':self.repeat_count,'nodes':self.nodes,'edges':self.edges},ensure_ascii=False,indent=2),encoding='utf-8'); self.refresh(); self.say('已保存 '+self.case.name); return True
    def persist(self):
        if self.case:
            self.case.write_text(json.dumps({'version':2,'repeat_count':self.repeat_count,'nodes':self.nodes,'edges':self.edges},ensure_ascii=False,indent=2),encoding='utf-8')
    def add(self,kind=None,x=None,y=None):
        if not self.case:
            self.new_case()
            if not self.case:return
        if self.selected is not None and not self.apply():return
        kind=kind or 'wait'; n=len(self.nodes)
        if x is None: x=self.canvas.canvasx(self.canvas.winfo_width()/2)/self.zoom-78
        if y is None: y=self.canvas.canvasy(self.canvas.winfo_height()/2)/self.zoom-40
        self.nodes.append({'id':uuid.uuid4().hex,'type':kind,'x':round(x),'y':round(y),'params':dict(TYPES[kind][1])})
        self.selected=n;self.selected_edge=None;self.show_params();self.draw();self.persist();self.say('已添加节点，拖动右侧圆点连接到另一节点左侧圆点')
    def copy_node(self,index=None):
        index=self.selected if index is None else index
        if index is None or not 0<=index<len(self.nodes): return
        if self.selected is not None and not self.apply():return
        self.persist(); self.node_clipboard=copy.deepcopy(self.nodes[index]); self.say('节点已复制；按 Ctrl+V 或右键空白处粘贴')
    def paste_node(self,x=None,y=None):
        if not self.node_clipboard:return
        if not self.case:
            self.new_case()
            if not self.case:return
        if self.selected is not None and not self.apply():return
        node=copy.deepcopy(self.node_clipboard);node['id']=uuid.uuid4().hex
        node['x']=round(x if x is not None else node['x']+35);node['y']=round(y if y is not None else node['y']+35)
        self.nodes.append(node);self.node_clipboard=copy.deepcopy(node);self.selected=len(self.nodes)-1;self.selected_edge=None
        self.show_params();self.persist();self.draw();self.say('节点已粘贴，参数已复制，连线请自行连接')
    def duplicate_node(self,index=None):
        self.copy_node(index);self.paste_node()
    def delete_selection(self):
        if self.selected_edge is not None:self.delete_edge(self.selected_edge)
        else:self.delete()
    def zoom_at(self,x,y,new):
        old=self.zoom;new=max(.15,min(2.5,new))
        if new==old:return
        wx=self.canvas.canvasx(x)/old;wy=self.canvas.canvasy(y)/old;self.zoom=new
        bound=10000*new;self.canvas.configure(scrollregion=(-bound,-bound,bound,bound))
        self.canvas.xview_moveto((wx*new-x+bound)/(2*bound));self.canvas.yview_moveto((wy*new-y+bound)/(2*bound))
        self.zoom_label.config(text=f'{new:.0%}');self.draw()
    def zoom_canvas(self,event):
        self.zoom_at(event.x,event.y,self.zoom*(1.12 if event.delta>0 else 1/1.12));return 'break'
    def zoom_center(self,factor):
        self.zoom_at(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,self.zoom*factor)
    def fit_canvas(self):
        if not self.nodes:return
        if not self.commit_current():return
        try:ordered=layout_order({'nodes':self.nodes,'edges':self.edges})
        except ValueError as e:self.say('无法整理布局：'+str(e));return
        width=max(1,self.canvas.winfo_width());height=max(1,self.canvas.winfo_height());ratio=width/height
        columns=max(1,min(6,len(ordered),math.ceil(math.sqrt(len(ordered)*ratio*155/220))))
        for index,node in enumerate(ordered):node['x']=(index%columns)*220;node['y']=(index//columns)*155
        self.persist();left=-35;top=-35;right=max(n['x']+180 for n in ordered)+35;bottom=max(n['y']+84 for n in ordered)+35
        self.zoom=max(.15,min(2.5,width/(right-left),height/(bottom-top)));z=self.zoom;bound=10000*z
        self.canvas.configure(scrollregion=(-bound,-bound,bound,bound));self.zoom_label.config(text=f'{z:.0%}')
        self.canvas.xview_moveto((((left+right)/2)*z-width/2+bound)/(2*bound));self.canvas.yview_moveto((((top+bottom)/2)*z-height/2+bound)/(2*bound));self.draw();self.say('已按连线顺序紧凑横向整理并适应画布')
    def unlink(self):
        if self.selected is None:return
        key=self.nodes[self.selected]['id']; self.edges=[e for e in self.edges if e['from']!=key and e['to']!=key];self.draw();self.persist();self.say('已移除相关连线')
    def context_menu(self,e):
        x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
        items=self.canvas.find_overlapping(x-8,y-8,x+8,y+8); target=None; edge_idx=None
        for item in reversed(items):
            for tag in self.canvas.gettags(item):
                if tag.startswith('edge:'):edge_idx=int(tag[5:]);break
                if tag.startswith('n') and tag[1:].isdigit():target=int(tag[1:]);break
            if target is not None or edge_idx is not None:break
        menu=tk.Menu(self,tearoff=False)
        for kind,(label,_) in TYPES.items(): menu.add_command(label='＋ '+label,command=lambda k=kind:self.add(k,x/self.zoom,y/self.zoom))
        if self.node_clipboard is not None:
            menu.add_separator();menu.add_command(label='粘贴节点',command=lambda:self.paste_node(x/self.zoom,y/self.zoom))
        if edge_idx is not None:
            menu.add_separator(); menu.add_command(label='删除这条连线',command=lambda i=edge_idx:self.delete_edge(i))
        if target is not None:
            menu.add_separator();menu.add_command(label='复制节点',command=lambda i=target:self.copy_node(i));menu.add_command(label='复制并粘贴',command=lambda i=target:self.duplicate_node(i));menu.add_command(label='删除节点',command=lambda i=target:self.delete_at(i));menu.add_command(label='断开节点连线',command=lambda i=target:self.unlink_at(i))
        try:menu.tk_popup(e.x_root,e.y_root)
        finally:menu.grab_release()
    def delete_edge(self,index):
        if 0<=index<len(self.edges):self.edges.pop(index);self.selected_edge=None;self.persist();self.draw();self.say('连线已删除')
    def unlink_at(self,index):
        if not self.commit_current():return
        self.selected=index;self.unlink();self.show_params()
    def delete_at(self,index):
        if not self.commit_current():return
        self.selected=index;self.delete()
    def draw(self):
        self.canvas.delete('all')
        lookup={n['id']:n for n in self.nodes}
        try: order=execution_order({'nodes':self.nodes,'edges':self.edges}); positions={n['id']:i+1 for i,n in enumerate(order)}
        except ValueError: positions={}
        for idx,edge in enumerate(self.edges):
            if edge['from'] not in lookup or edge['to'] not in lookup:continue
            p,q=lookup[edge['from']],lookup[edge['to']];z=self.zoom;x1,y1=(p['x']+180)*z,(p['y']+42)*z;x2,y2=q['x']*z,(q['y']+42)*z
            bend=max(65*z,abs(x2-x1)*.45)
            if abs((x1-180*z)-x2)<1*z and y2-y1>84*z:
                lane=(y1+42*z+y2-42*z)/2
                points=(x1,y1,x1+30*z,y1,x1+30*z,lane,x2-30*z,lane,x2-30*z,y2,x2,y2)
            elif x2<x1 and y2-y1>84*z:
                lane=(y1+42*z+y2-42*z)/2
                points=(x1,y1,x1+30*z,y1,x1+30*z,lane,x2-30*z,lane,x2-30*z,y2,x2,y2)
            elif x2>=x1 and abs(y2-y1)<1*z:points=(x1,y1,x2,y2)
            else:points=(x1,y1,x1+bend,y1,x2-bend,y2,x2,y2)
            self.canvas.create_line(*points,fill='#e78725' if idx==self.selected_edge else '#6c92c4',width=max(2,3*z),smooth=True,splinesteps=24,arrow='last',tags=('edge:'+str(idx),))
        for i,n in enumerate(self.nodes):
            z=self.zoom;x,y=n['x']*z,n['y']*z;tag='n'+str(i);pos=positions.get(n['id'],'–')
            state=self.node_status.get(n['id']) if self.case==self.run_case_path else None
            palette={'pending':('#ffffff','#cdd8e7','#edf1f7','#78869a','待执行'),'running':('#eff6ff','#2563eb','#dbeafe','#1d4ed8','运行中'),'success':('#f0fdf4','#52ad75','#dcfce7','#168052','完成'),'error':('#fff1f1','#dc4f4f','#fee2e2','#bb3030','失败'),'skipped':('#f6f7f9','#ccd3db','#eceff3','#7b8795','未执行')}
            color,border,header,ink,status=palette.get(state,('#edf4ff' if i==self.selected else '#ffffff','#79a9e6' if i==self.selected else '#cdd8e7','#dceaff' if i==self.selected else '#edf1f7','#71839a',''))
            self.canvas.create_rectangle(x,y,x+180*z,y+84*z,fill=color,outline=border,width=3 if state=='running' else 2,tags=(tag,'status:'+str(state)))
            self.canvas.create_rectangle(x,y,x+180*z,y+29*z,fill=header,outline='',tags=(tag,))
            self.canvas.create_text(x+12*z,y+15*z,anchor='w',text=f'{pos}  {TYPES.get(n["type"],("未知节点",))[0]}',fill='#203653',width=160*z,font=('Microsoft YaHei UI',max(6,round(10*z)),'bold'),tags=(tag,))
            self.canvas.create_text(x+14*z,y+57*z,anchor='w',text='输入',fill='#71839a',font=('Microsoft YaHei UI',max(6,round(9*z))),tags=(tag,)); self.canvas.create_text(x+166*z,y+57*z,anchor='e',text='输出',fill='#71839a',font=('Microsoft YaHei UI',max(6,round(9*z))),tags=(tag,))
            if state:
                result=self.node_results.get(n['id'],'');result=result if len(result)<=24 else result[:23]+'…'
                self.canvas.create_text(x+90*z,y+(45 if result else 57)*z,text=status,fill=ink,font=('Microsoft YaHei UI',max(6,round(8*z)),'bold'),tags=(tag,'run-label'))
                if result:self.canvas.create_text(x+90*z,y+69*z,text=result,fill=ink,width=145*z,font=('Microsoft YaHei UI',max(5,round(7*z))),tags=(tag,'run-result'))
            self.canvas.create_oval(x-7*z,y+35*z,x+7*z,y+49*z,fill='#ffffff',outline='#538ccc',width=2,tags=(tag,'in:'+n['id']))
            self.canvas.create_oval(x+173*z,y+35*z,x+187*z,y+49*z,fill='#ffffff',outline='#538ccc',width=2,tags=(tag,'out:'+n['id']))
    def cancel_hover_hide(self,event=None):
        if self.hide_timer is not None:self.after_cancel(self.hide_timer);self.hide_timer=None
    def schedule_hover_hide(self):
        if self.hover_timer is not None:self.after_cancel(self.hover_timer);self.hover_timer=None
        if self.hover_window is None:self.hover_key=None;return
        self.cancel_hover_hide();self.hide_timer=self.after(350,self.check_hover_pointer)
    def check_hover_pointer(self):
        self.hide_timer=None
        if not self.hover_window:return
        x,y=self.winfo_pointerxy();w=self.hover_window
        inside=w.winfo_rootx()<=x<w.winfo_rootx()+w.winfo_width() and w.winfo_rooty()<=y<w.winfo_rooty()+w.winfo_height()
        if inside:self.hide_timer=self.after(350,self.check_hover_pointer)
        else:self.hide_hover()
    def hide_hover(self):
        if self.hover_timer is not None:self.after_cancel(self.hover_timer);self.hover_timer=None
        self.cancel_hover_hide()
        if self.hover_window is not None:self.hover_window.destroy();self.hover_window=None
        self.hover_photo=None;self.hover_key=None
    def canvas_hover(self,event):
        if self.drag or self.case!=self.preview_case_path:
            if self.hover_window:self.schedule_hover_hide()
            return
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y);key=None
        for item in reversed(self.canvas.find_overlapping(x,y,x,y)):
            for tag in self.canvas.gettags(item):
                if tag.startswith('n') and tag[1:].isdigit():
                    node=self.nodes[int(tag[1:])]
                    if node['type']=='capture' and self.node_artifacts.get(node['id']):key=node['id']
                    break
            if key:break
        if not key:
            if self.hover_timer is not None:self.after_cancel(self.hover_timer);self.hover_timer=None
            if self.hover_window:self.schedule_hover_hide()
            else:self.hover_key=None
            return
        self.cancel_hover_hide()
        if key==self.hover_key:return
        if self.hover_timer is not None:self.after_cancel(self.hover_timer)
        self.hover_key=key;self.hover_timer=self.after(250,lambda k=key,x=event.x_root,y=event.y_root:self.show_hover(k,x,y))
    def show_hover(self,key,x,y):
        self.hover_timer=None
        if key!=self.hover_key:return
        path=self.node_artifacts.get(key)
        try:
            with Image.open(path) as source:
                image=source.copy();image.thumbnail((300,180),Image.Resampling.LANCZOS)
        except (OSError,ValueError,TypeError):return
        if self.hover_window:self.hover_window.destroy()
        popup=tk.Toplevel(self);self.hover_window=popup;popup.overrideredirect(True);popup.configure(bg='#cbd6e4')
        frame=tk.Frame(popup,bg='#ffffff',padx=6,pady=6);frame.pack(padx=1,pady=1)
        self.hover_photo=ImageTk.PhotoImage(image,master=popup);label=tk.Label(frame,image=self.hover_photo,bg='#ffffff',cursor='hand2');label.pack()
        button=ttk.Button(frame,text='放大查看',command=lambda p=path:self.show_large_image(p));button.pack(fill='x',pady=(4,0))
        label.bind('<Button-1>',lambda e,p=path:self.show_large_image(p))
        for widget in (popup,frame,label,button):
            widget.bind('<Enter>',self.cancel_hover_hide,add='+');widget.bind('<Leave>',lambda e:self.schedule_hover_hide(),add='+')
        popup.update_idletasks();left=min(x+18,max(0,popup.winfo_screenwidth()-popup.winfo_reqwidth()-10));top=min(y+18,max(0,popup.winfo_screenheight()-popup.winfo_reqheight()-10))
        popup.geometry(f'+{left}+{top}');self.cancel_hover_hide();self.hide_timer=self.after(350,self.check_hover_pointer)
    def hit_tag(self,x,y,prefix):
        for item in reversed(self.canvas.find_overlapping(x-6,y-6,x+6,y+6)):
            for tag in self.canvas.gettags(item):
                if tag.startswith(prefix):return tag[len(prefix):]
        return None
    def click(self,e):
        self.canvas.focus_set();x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
        source=self.hit_tag(x,y,'out:'); target=self.hit_tag(x,y,'in:')
        if source or target:
            key=source or target;node=next(n for n in self.nodes if n['id']==key);self.drag=('wire',key,(node['x']+(180 if source else 0))*self.zoom,(node['y']+42)*self.zoom,'out' if source else 'in');return
        for item in reversed(self.canvas.find_overlapping(x,y,x,y)):
            for tag in self.canvas.gettags(item):
                if tag.startswith('n') and tag[1:].isdigit():
                    index=int(tag[1:])
                    if self.selected is not None and self.selected!=index:
                        if not self.apply():return
                        self.persist()
                    self.selected=index;self.selected_edge=None;node=self.nodes[index];self.drag=('node',index,x/self.zoom-node['x'],y/self.zoom-node['y']);self.show_params();self.draw();return
        edge=self.hit_tag(x,y,'edge:')
        if edge is not None:
            if self.selected is not None:
                if not self.apply():return
                self.persist()
            self.selected=None;self.selected_edge=int(edge);self.show_params();self.draw();self.say('已选择连线，按 Delete 删除');return
        self.selected_edge=None;self.draw();self.drag=('pan',);self.canvas.scan_mark(e.x,e.y);self.canvas.configure(cursor='fleur')
    def move(self,e):
        if not self.drag:return
        x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
        if self.drag[0]=='pan': self.canvas.scan_dragto(e.x,e.y,gain=1)
        elif self.drag[0]=='node':
            _,i,dx,dy=self.drag;self.nodes[i]['x']=round(x/self.zoom-dx);self.nodes[i]['y']=round(y/self.zoom-dy);self.draw()
        elif self.drag[0]=='wire':
            self.canvas.delete('draft-wire');_,_,x1,y1,_=self.drag;bend=max(65,abs(x-x1)*.45)
            self.canvas.create_line(x1,y1,x1+bend,y1,x-bend,y,x,y,fill='#3176cc',width=3,smooth=True,arrow='last',tags=('draft-wire',))
    def release(self,e):
        drag=self.drag;self.drag=None;self.canvas.configure(cursor='');self.canvas.delete('draft-wire')
        if not drag:return
        if drag[0]=='node':self.persist()
        if drag[0]=='wire':
            x,y=self.canvas.canvasx(e.x),self.canvas.canvasy(e.y)
            if drag[4]=='out':source=drag[1];target=self.hit_tag(x,y,'in:')
            else:target=drag[1];source=self.hit_tag(x,y,'out:')
            if source and target and target!=source:
                edges=[edge for edge in self.edges if edge['from']!=source and edge['to']!=target]
                successor={edge['from']:edge['to'] for edge in edges};current=target;seen=set()
                while current in successor and current not in seen:seen.add(current);current=successor[current]
                if current==source:
                    self.say('不能连接：该连线会形成循环');self.draw();return
                changed=len(edges)!=len(self.edges);edges.append({'from':source,'to':target});self.edges=edges;self.selected_edge=None;self.persist();self.draw();self.say('已连接节点'+('，原端口连线已替换' if changed else ''))
    def show_params(self):
        for widget in self.param_frame.winfo_children(): widget.destroy()
        self.param_vars={}; self.param_types={}
        if self.selected is None:return
        node=self.nodes[self.selected]; params=dict(TYPES.get(node['type'],('',{}))[1]); params.update(node['params'])
        labels={'port':'串口','channel':'通道','seconds':'等待秒数（可小数）','ini':'初始化 INI','firmware':'固件 BIN','slave':'设备地址','register':'寄存器','address_bits':'地址位宽','data_bits':'数据位宽','value':'写入数值','expected':'期望值（可空）','mask':'断言掩码','fps_min':'帧率下限','fps_max':'帧率上限','dn_min':'DN 下限','dn_max':'DN 上限','output':'输出路径 / 前缀','source':'原始固件','address':'读取起始地址','length':'读取字节数','offset':'修改偏移','hex_bytes':'十六进制字节'}
        row=0
        for key,value in params.items():
            if key=='data_bits' and node['type'] in ('i2c_read','i2c_write'):continue
            if key=='address_bits' and node['type'] in ('i2c_read','i2c_write'):
                address_bits=params['address_bits'];data_bits=params['data_bits']
                self.param_vars['address_bits']=tk.StringVar(value=str(address_bits));self.param_types['address_bits']=int
                self.param_vars['data_bits']=tk.StringVar(value=str(data_bits));self.param_types['data_bits']=int
                fmt=tk.StringVar(value=f'A{int(address_bits)//8}D{int(data_bits)//8}')
                ttk.Label(self.param_frame,text='读写格式').grid(row=row,column=0,sticky='w',pady=2)
                combo=ttk.Combobox(self.param_frame,textvariable=fmt,state='readonly',width=18,values=['A1D1','A1D2','A2D1','A2D2','A2D4'])
                combo.grid(row=row,column=1,sticky='ew',padx=4,pady=2)
                def update_format(event=None):
                    selected=fmt.get();self.param_vars['address_bits'].set(str(int(selected[1])*8));self.param_vars['data_bits'].set(str(int(selected[3])*8))
                combo.bind('<<ComboboxSelected>>',update_format)
                ttk.Label(self.param_frame,text='A：地址字节数  D：数据字节数',foreground='#6a7c93').grid(row=row+1,column=1,sticky='w',padx=4);row+=2;continue
            label='存图目录 / 文件名前缀' if key=='output' and node['type']=='capture' else labels.get(key,key)
            ttk.Label(self.param_frame,text=label).grid(row=row,column=0,sticky='w',pady=2)
            var=tk.StringVar(value=str(value)); self.param_vars[key]=var; self.param_types[key]=type(value)
            ttk.Entry(self.param_frame,textvariable=var,width=20).grid(row=row,column=1,sticky='ew',padx=4,pady=2)
            if key in ('ini','firmware','source','output'):
                ttk.Button(self.param_frame,text='…',width=2,command=lambda k=key:self.browse_param(k)).grid(row=row,column=2)
            row+=1
        self.param_frame.columnconfigure(1,weight=1)
    def browse_param(self,key):
        if key=='output' and self.selected is not None and self.nodes[self.selected]['type']=='capture':
            folder=filedialog.askdirectory(title='选择抓图保存目录'); path=str(pathlib.Path(folder)/'capture') if folder else ''
        elif key=='output':path=filedialog.asksaveasfilename(title='选择输出文件')
        else:path=filedialog.askopenfilename(title='选择文件')
        if path:self.param_vars[key].set(path)
    def apply(self):
        if self.selected is None:return
        try:
            values={}
            for key,var in self.param_vars.items():
                value=var.get(); typ=self.param_types[key]
                if key=='seconds' and self.nodes[self.selected]['type']=='wait':
                    value=float(value)
                    if not math.isfinite(value) or not 0<=value<=86400:raise ValueError('等待时间须为 0 到 86400 秒的数字，例如 0.07')
                elif typ is int: value=int(value,0)
                elif typ is float: value=float(value)
                values[key]=value
            self.nodes[self.selected]['params']=values; self.say('参数已应用，请保存 Case'); return True
        except Exception as e:messagebox.showerror('参数错误',str(e)); return False
    def delete(self):
        if self.selected is not None:
            key=self.nodes[self.selected]['id']; self.nodes.pop(self.selected); self.edges=[e for e in self.edges if e['from']!=key and e['to']!=key]; self.selected=None; self.selected_edge=None; self.show_params(); self.draw(); self.persist()
    def check(self):
        resolved=resolve_paths({'nodes':self.nodes,'edges':self.edges},self.case or ROOT/'case.json',ROOT)
        validate_steps(execution_order(resolved))
    def validate(self):
        try:
            if self.selected is not None and not self.apply():return
            self.check(); self.say('流程校验通过：节点顺序和参数有效；尚未执行硬件操作。')
        except Exception as e:messagebox.showerror('校验失败',str(e)); self.say('校验失败：'+str(e))
    def render_event(self,event):
        self.step_update(event)
        if not self.simulating:
            key=self.run_node_ids.get(event.get('index'));kind=event.get('event')
            if key and kind in ('step_start','step_done','step_error'):
                self.node_status[key]={'step_start':'running','step_done':'success','step_error':'error'}[kind]
                if kind=='step_start':self.node_results.pop(key,None)
                elif kind=='step_done':
                    self.node_results[key]='抓图完成' if event.get('type')=='capture' else str(event.get('message',''))
                    if event.get('type')=='capture' and event.get('artifacts',{}).get('preview'):self.node_artifacts[key]=event['artifacts']['preview']
                else:self.node_results[key]=str(event.get('message','执行失败'))
                if self.case==self.run_case_path:self.draw()
        kind=event.get('event');typ=event.get('type');label=TYPES.get(typ,(typ,))[0]
        if kind=='step_start':
            p=event.get('params',{});now=event.get('_recorded_at') or ('--:--:--' if self.replaying else datetime.datetime.now().strftime('%H:%M:%S'))
            self.log_append(f"\n{now}   {event['index']:02d} / {event['total']:02d}   {label}",'heading')
            if typ in ('i2c_read','i2c_write'):
                self.log_append(f"从设备 {p.get('slave')}    寄存器 {p.get('register')}")
                self.log_append(f"A{int(p.get('address_bits',0))//8}D{int(p.get('data_bits',0))//8}  ·  地址 {p.get('address_bits')} 位  ·  数据 {p.get('data_bits')} 位",'muted')
                if typ=='i2c_write':self.log_append(f"写入值  {p.get('value')}",'value')
                if typ=='i2c_read':
                    if p.get('expected','')!='':self.log_append(f"期望值 {p['expected']}  ·  掩码 {p.get('mask','默认')}",'muted')
                    else:self.log_append('仅读取，未设置期望值断言','muted')
            elif typ in ('relay_on','relay_off'):self.log_append(f"{p.get('port')}  ·  Channel {p.get('channel')}",'muted')
            elif typ=='wait':
                seconds=p.get('seconds'); self.log_append(f'等待 {seconds} 秒（{seconds*1000:g} 毫秒）' if isinstance(seconds,(int,float)) and seconds<1 else f'等待 {seconds} 秒','muted')
            elif typ in ('firmware','firmware_backup','power_on'):
                if p.get('ini'):self.log_append(f"配置：{p['ini']}",'path')
                if p.get('firmware'):self.log_append(f"固件：{p['firmware']}",'path')
            elif typ=='capture':self.log_append(f"保存前缀：{p.get('output','')}",'path')
        elif kind=='step_done':
            elapsed=event.get('elapsed',0);message=event.get('message','完成');duration=f'{elapsed*1000:.1f} 毫秒' if elapsed<1 else f'{elapsed:.3f} 秒'
            if typ=='capture':
                self.log_append(f'✓ 抓图完成  ·  {duration}','success')
                artifacts=event.get('artifacts',{});raw=artifacts.get('raw');preview=artifacts.get('preview')
                if raw:self.last_image_dir=pathlib.Path(raw).parent;self.log_append('原始帧：','muted');self.log_append(raw,'path')
                if preview:self.last_preview=pathlib.Path(preview);self.log_append('预览图片：','muted');self.log_append(preview,'path');self.add_log_preview(preview)
                if '预览生成失败' in message:self.log_append(message.split('；')[-1],'error')
            else:
                self.log_append(f'✓ {message}  ·  {duration}','value' if typ in ('i2c_read','i2c_write','metrics') else 'success')
        elif kind=='step_error':
            self.step_failed=True;self.log_append('✕ '+event.get('message','执行失败')+('（继续执行后续步骤）' if event.get('continued') else ''),'error')
    def run_real(self,continuing=False):
        if self.process:return messagebox.showwarning('正在运行','请等待当前 Case 完成')
        if self.batch and not continuing:return messagebox.showwarning('正在运行','请等待重复执行完成')
        try:
            if not self.case:raise ValueError('请先保存 Case')
            if not continuing:
                if not self.save():return
                self.check()
                self.batch={'total':self.repeat_count,'current':1,'failed_rounds':0,'id':uuid.uuid4().hex,'case_data':copy.deepcopy({'version':2,'repeat_count':self.repeat_count,'nodes':self.nodes,'edges':self.edges})}
            env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['CANVAS_APP_DIR']=str(ROOT)
            runid=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            run_dir=self.case.parent/'测试结果'/self.case.name.removesuffix('.case.json')/runid
            run_dir.mkdir(parents=True,exist_ok=False);self.current_run_dir=run_dir;self.last_image_dir=None;self.last_preview=None;self.step_failed=False
            logs_dir=run_dir/'日志';config_dir=run_dir/'配置';logs_dir.mkdir();config_dir.mkdir()
            self.raw_log_path=logs_dir/'底层完整日志.log';snapshot=config_dir/'执行快照.json';self.run_summary_path=run_dir/'运行摘要.json'
            snapshot_data=resolve_paths(self.batch['case_data'],self.case,ROOT,run_dir)
            snapshot.write_text(json.dumps(snapshot_data,ensure_ascii=False,indent=2),encoding='utf-8')
            if getattr(sys,'frozen',False):
                env['CANVAS_SDK_DIR']=env.get('CANVAS_SDK_DIR',str(ROOT/'sdk'))
                command=[str(ROOT/'runner_v6'/'设备执行器.exe'),str(snapshot)]
            else:command=[sys.executable,'-u',str(ROOT/'hardware_runner.py'),str(snapshot)]
            self.runlog=self.raw_log_path.open('w',encoding='utf-8');self.runlog.write('Case: '+str(self.case)+'\n');self.runlog.flush()
            self.readable_log=(logs_dir/'执行记录.txt').open('w',encoding='utf-8');self.event_file=(logs_dir/'步骤事件.jsonl').open('w',encoding='utf-8')
            self.run_failures=[];self.run_summary={'status':'运行中','case':str(self.case),'started_at':datetime.datetime.now().isoformat(timespec='microseconds'),'exit_code':None,'failed_count':0,'failures':[],'batch_id':self.batch['id'],'repeat_index':self.batch['current'],'repeat_total':self.batch['total']}
            self.run_summary_path.write_text(json.dumps(self.run_summary,ensure_ascii=False,indent=2),encoding='utf-8')
            self.history_nav.pack_forget();self.clear_log();self.reset_overview();self.run_status.config(text='运行中',foreground='#a86508')
            planned=execution_order(snapshot_data);self.run_case_path=self.case;self.preview_case_path=self.case;self.run_node_ids={i:node['id'] for i,node in enumerate(planned,1)};self.node_status={node['id']:'pending' for node in planned};self.node_results={};self.node_artifacts={};self.hide_hover();self.draw();self.simulating=True
            for i,node in enumerate(planned,1):self.step_update({'event':'step_start','index':i,'total':len(planned),'type':node['type'],'params':node['params']})
            self.simulating=False
            self.log_append('开始执行  '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'heading')
            self.log_append('Case：'+self.case.name.removesuffix('.case.json')+f"  ·  第 {self.batch['current']} / {self.batch['total']} 轮",'muted')
            self.log_append('本次结果目录：','muted');self.log_append(str(run_dir),'path')
            self.process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));proc=self.process
            def reader():
                for line in proc.stdout:self.messages.put(line.rstrip())
                self.messages.put(('exit',proc.wait()))
            threading.Thread(target=reader,daemon=True).start();self.refresh_history();self.say(f"正在执行 Case · 第 {self.batch['current']} / {self.batch['total']} 轮");self.after(100,self.poll_runner)
        except Exception as e:
            if self.runlog:self.runlog.close();self.runlog=None
            if self.readable_log:self.readable_log.close();self.readable_log=None
            if self.event_file:self.event_file.close();self.event_file=None
            if self.run_summary:
                self.run_summary.update(status='启动失败',error=str(e));self.run_summary_path.write_text(json.dumps(self.run_summary,ensure_ascii=False,indent=2),encoding='utf-8');self.run_summary=None
            self.batch=None
            self.run_status.config(text='启动失败',foreground='#be3535');self.log_append('✕ 无法运行：'+str(e),'error');messagebox.showerror('无法运行',str(e))
    def poll_runner(self):
        try:
            while True:
                m=self.messages.get_nowait()
                if isinstance(m,tuple):
                    self.process=None;success=m[1]==0 and not self.run_failures
                    completed_with_failures=m[1]==2 or (m[1]==0 and bool(self.run_failures))
                    summary='运行成功' if success else '执行完成 · 有失败' if completed_with_failures else '运行中断'
                    if not success:
                        for key,state in list(self.node_status.items()):
                            if state in ('pending','running'):self.node_status[key]='skipped' if state=='pending' else 'error';self.node_results[key]='' if state=='pending' else '执行中断'
                        if self.case==self.run_case_path:self.draw()
                        for row in self.steps.get_children():
                            values=list(self.steps.item(row,'values'))
                            if values[2] in ('待执行','运行中'):
                                values[2]='未执行' if values[2]=='待执行' else '中断';self.steps.item(row,values=values,tags=('error',) if values[2]=='中断' else ())
                    self.run_status.config(text=summary,foreground='#168052' if success else '#be3535');self.say(summary+'，退出码：'+str(m[1]))
                    self.log_append('\n'+('✓ ' if success else '✕ ')+summary+('  ·  '+str(len(self.run_failures))+' 个步骤失败' if self.run_failures else '')+'  ·  退出码 '+str(m[1]),'success' if success else 'error')
                    if self.runlog:self.runlog.write('退出码：'+str(m[1])+'\n');self.runlog.close();self.runlog=None
                    if self.readable_log:self.readable_log.close();self.readable_log=None
                    if self.event_file:self.event_file.close();self.event_file=None
                    if self.run_summary:
                        self.run_summary.update(status='通过' if success else '有失败' if completed_with_failures else '中断',exit_code=m[1],failed_count=len(self.run_failures),failures=self.run_failures,finished_at=datetime.datetime.now().isoformat(timespec='seconds'))
                        self.run_summary_path.write_text(json.dumps(self.run_summary,ensure_ascii=False,indent=2),encoding='utf-8');self.run_summary=None
                    self.refresh_history()
                    if self.batch:
                        batch=self.batch
                        if not success:batch['failed_rounds']+=1
                        if (success or completed_with_failures) and batch['current']<batch['total']:
                            batch['current']+=1;self.run_real(continuing=True);return
                        if batch['total']>1:
                            text=f"重复执行结束：{batch['current']} / {batch['total']} 轮，{batch['failed_rounds']} 轮失败"
                            if not success and not completed_with_failures:text+='（关键步骤中断）'
                            self.say(text);self.run_status.config(text=text,foreground='#be3535' if batch['failed_rounds'] else '#168052');self.log_append(text,'error' if batch['failed_rounds'] else 'success')
                        self.batch=None
                    return
                if self.runlog:self.runlog.write(m+'\n');self.runlog.flush()
                if m.startswith('@@CANVAS_EVENT@@'):
                    try:
                        event=json.loads(m[len('@@CANVAS_EVENT@@'):]);event['_recorded_at']=datetime.datetime.now().strftime('%H:%M:%S')
                        if self.event_file:self.event_file.write(json.dumps(event,ensure_ascii=False)+'\n');self.event_file.flush()
                        if event.get('event')=='step_error':self.run_failures.append({'index':event.get('index'),'type':event.get('type'),'message':event.get('message'),'continued':bool(event.get('continued'))})
                        self.render_event(event)
                    except (ValueError,KeyError,TypeError) as e:self.log_append('日志解析失败：'+str(e),'error')
                elif 'StructuredException.cpp:180' in m or 'StructuredException.cpp:183' in m:pass
                elif m.startswith('执行失败：'):
                    if not self.step_failed:self.log_append('✕ '+m,'error')
                elif '[error]' in m.lower() or '[critical]' in m.lower():self.log_append(m,'error')
                elif m and not re.match(r'^\[20\d\d-\d\d-\d\d ',m) and not m.startswith(('#','(Build','真实流程完成')):self.log_append(m,'muted')
                # Native DLL diagnostics remain available in the complete log.
        except queue.Empty:pass
        self.after(100,self.poll_runner)
    def simulate(self):
        try:
            if self.selected is not None and not self.apply():return
            self.check()
        except Exception as e:return messagebox.showerror('无法模拟',str(e))
        self.clear_log();self.reset_overview();self.run_case_path=None;self.preview_case_path=None;self.node_artifacts={};self.hide_hover();self.node_status={};self.node_results={};self.draw();self.simulating=True;self.run_status.config(text='模拟',foreground='#65758d');self.log_append('模拟运行 · 不会控制设备','heading')
        nodes=execution_order({'nodes':self.nodes,'edges':self.edges})
        for i,n in enumerate(nodes,1):self.render_event({'event':'step_start','index':i,'total':len(nodes),'type':n['type'],'params':n['params']})
        self.simulating=False;self.log_append('\n模拟完成','success')

if __name__=='__main__': App().mainloop()
