"""Read prior run artifacts without changing cases or modifying historical files."""
import json
from datetime import datetime
from pathlib import Path

def inspect_run(directory):
 directory=Path(directory);snapshot=directory/'配置'/'执行快照.json'
 if not snapshot.is_file():snapshot=directory/'执行快照.json'
 raw=directory/'日志'/'底层完整日志.log'
 if not raw.is_file():raw=directory/'底层完整日志.log'
 detail=directory/'日志'/'执行记录.txt'
 if not detail.is_file():detail=directory/'执行记录.txt'
 events_path=directory/'日志'/'步骤事件.jsonl';summary_path=directory/'运行摘要.json'
 summary={}
 if summary_path.is_file():
  try:summary=json.loads(summary_path.read_text(encoding='utf-8'))
  except (OSError,ValueError):pass
 events=[];exit_code=summary.get('exit_code')
 try:
  if events_path.is_file():
   with events_path.open(encoding='utf-8') as f:
    for line in f:
     try:events.append(json.loads(line))
     except ValueError:continue
  elif raw.is_file():
   with raw.open(encoding='utf-8',errors='replace') as f:
    for line in f:
     if line.startswith('@@CANVAS_EVENT@@'):
      try:events.append(json.loads(line[len('@@CANVAS_EVENT@@'):]))
      except ValueError:pass
     elif line.startswith('退出码：'):
      try:exit_code=int(line.split('：',1)[1].strip())
      except ValueError:pass
 except OSError:pass
 failed=sum(1 for e in events if e.get('event')=='step_error')
 status=summary.get('status') or ('通过' if exit_code==0 else '有失败' if exit_code==2 else '失败' if exit_code is not None else '未知')
 if status=='运行中':status='未结束'
 return {'directory':directory,'snapshot':snapshot,'raw':raw,'detail':detail,'events':events,'status':status,'failed':summary.get('failed_count',failed),'exit_code':exit_code,'repeat_index':summary.get('repeat_index',1),'repeat_total':summary.get('repeat_total',1),'batch_id':summary.get('batch_id'),'started_at':summary.get('started_at','')}

def run_time(run):
 """Compare modern ISO timestamps and legacy timestamped folder names equally."""
 try:
  if run['started_at']:return datetime.fromisoformat(run['started_at']).replace(tzinfo=None)
 except (ValueError,TypeError):pass
 try:return datetime.strptime(run['directory'].name[:15],'%Y%m%d-%H%M%S')
 except (ValueError,TypeError):return datetime.min

def list_runs(case_path):
 case=Path(case_path);base=case.parent/'测试结果'/case.name.removesuffix('.case.json')
 if not base.is_dir():return []
 runs=[inspect_run(p) for p in base.iterdir() if p.is_dir()]
 return sorted(runs,key=lambda r:(run_time(r),r['repeat_index']),reverse=True)


def list_batches(case_path):
 """Group rounds by the execution click that produced them, retaining older runs."""
 groups={}
 for run in list_runs(case_path):
  key=run['batch_id'] or 'legacy:'+str(run['directory'])
  groups.setdefault(key,[]).append(run)
 result=[]
 for key,runs in groups.items():
  runs.sort(key=lambda r:r['repeat_index'])
  total=max([r['repeat_total'] for r in runs]+[len(runs)])
  passed=sum(r['status']=='通过' for r in runs)
  failed=sum(r['status'] in ('有失败','中断','失败','启动失败') for r in runs)
  unknown=len(runs)-passed-failed
  result.append({'id':key,'runs':runs,'total':total,'passed':passed,'failed':failed,'unknown':unknown,'not_run':max(0,total-len(runs)),'started_at':runs[0]['started_at'],'directory':runs[0]['directory']})
 return sorted(result,key=lambda b:run_time(b['runs'][0]),reverse=True)
