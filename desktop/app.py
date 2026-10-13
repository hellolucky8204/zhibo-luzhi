import asyncio, json, os, sys, re, shutil, signal, subprocess, threading, time, uuid
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import proxy_service
import desktop_controls
from stream_identity import room_key
from urllib.parse import urlparse, unquote, parse_qs
PORT=int(sys.argv[1]) if len(sys.argv)>1 else 8769
ROOT=Path(__file__).resolve().parent
from runtime_paths import DATA, RECORDINGS
DATA.mkdir(exist_ok=True)
RECORD=RECORDINGS; RECORD.mkdir(exist_ok=True)
LOCK=threading.RLock(); STOP=threading.Event(); JOBS={}; SESSIONS={}; STATUS={}; LOG=[]; WAKE={}; HEALTH={}
CONFIG=DATA/'anchors.json'
ANCHORS=json.loads(CONFIG.read_text()) if CONFIG.exists() else []
PROFILES={'360':450,'480':800,'720':1500}
def estimate_mb(mode,quality):
    kbps=(PROFILES[quality] if mode!='audio' else 0)+96+(96 if mode=='both' else 0)
    return round(kbps*3600/8/1000)

FFMPEG=shutil.which('ffmpeg') or str(Path.home()/'bin/ffmpeg')
def log(msg):
    with LOCK:
        LOG.append({'time':datetime.now().strftime('%H:%M:%S'),'message':msg}); del LOG[:-200]
def save():
    p=CONFIG.with_suffix('.tmp'); p.write_text(json.dumps(ANCHORS,ensure_ascii=False,indent=2)); p.replace(CONFIG)
def stop_job(key):
    p=JOBS.get(key)
    if p and p.poll() is None:
        try: p.stdin.write(b'q\n'); p.stdin.flush(); p.wait(timeout=10)
        except Exception: p.terminate(); p.wait(timeout=5)
    JOBS.pop(key,None)
async def douyin(url):
    from streamget import DouyinLiveStream
    live=DouyinLiveStream()
    data=await live.fetch_web_stream_data(url)
    obj=await live.fetch_stream_url(data,'OD')
    return (obj.m3u8_url or obj.flv_url) if obj.is_live else None

def resolve(a):
    if a['platform']=='抖音':
        if urlparse(a['url']).hostname != 'live.douyin.com':
            raise ValueError('第一版请填写 https://live.douyin.com/直播间ID；主页账号解析待接入')
        parts=urlparse(a['url'])
        rid=parse_qs(parts.query).get('live_web_rid',[''])[0]
        url='https://live.douyin.com/'+rid if rid.isdigit() else a['url']
        return asyncio.run(asyncio.wait_for(douyin(url),45))
    if a['platform']=='视频号' and a.get('capture_id'): return proxy_service.source(a.get('capture_room') or a['capture_id'])['url']
    if a['platform']=='视频号': raise ValueError('视频号账号自动解析尚未接入；已有直播流可选择“直播流”录制')
    return a['url']

def start_job(a,url):
    if shutil.disk_usage(RECORD).free < 1024**3: raise ValueError('磁盘剩余不足 1GB，停止新录制')
    name=re.sub(r'[^\w\-\u4e00-\u9fff]','_',a['name'])[:60]
    with LOCK:
        catalog_file=RECORD/'_catalog.json'
        try:catalog=json.loads(catalog_file.read_text()) if catalog_file.exists() else {}
        except (ValueError,OSError):catalog={}
        catalog[name]={'platform':a.get('platform','未标注'),'name':a['name']}
        temp_catalog=catalog_file.with_suffix('.tmp');temp_catalog.write_text(json.dumps(catalog,ensure_ascii=False));temp_catalog.replace(catalog_file)
    folder=RECORD/name/datetime.now().strftime('%Y-%m-%d'); folder.mkdir(parents=True,exist_ok=True)
    prefix=folder/(datetime.now().strftime('%H-%M-%S')+'-'+a['id'][:6]+'-'+str(time.time_ns()%1000000))
    quality=str(a.get('quality','360')); bitrate=PROFILES[quality]; height=int(quality)
    scale=rf'scale=w=if(gte(iw\,ih)\,-2\,trunc(min({height}\,iw)/2)*2):h=if(gte(iw\,ih)\,trunc(min({height}\,ih)/2)*2\,-2)'
    cmd=[FFMPEG,'-hide_banner','-loglevel','error','-y','-rw_timeout','15000000']
    if a.get('capture_id'):
        headers=proxy_service.source(a.get('capture_room') or a['capture_id']).get('headers',{})
        if headers:cmd+=['-headers',''.join(k+': '+v.replace('\r','').replace('\n','')+'\r\n' for k,v in headers.items())]
    cmd+=['-i',url]
    def output(audio):
        codec=(['-map','0:a:0','-vn','-c:a','aac','-b:a','96k'] if audio else ['-map','0:v:0','-map','0:a:0?','-vf',scale,'-c:v','libx264','-preset','veryfast','-b:v',str(bitrate)+'k','-maxrate',str(bitrate*2)+'k','-bufsize',str(bitrate*4)+'k','-pix_fmt','yuv420p','-force_key_frames','expr:gte(t,n_forced*1800)','-c:a','aac','-b:a','96k'])
        return codec+['-f','segment','-segment_time','1800','-reset_timestamps','1','-segment_format_options','movflags=+faststart',str(prefix)+('-%03d.m4a' if audio else '-%03d.mp4')]
    if a['mode'] in ('video','both'): cmd+=output(False)
    if a['mode'] in ('audio','both'): cmd+=output(True)
    # Keep raw engine errors local; never expose signed stream URLs in the UI.
    err=open(DATA/(a['id']+'.engine.log'),'ab')
    try:
        JOBS[a['id']]=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=err)
        SESSIONS[a['id']]={'started':time.time(),'prefix':str(prefix),'quality':quality}
        HEALTH[a['id']]={'last_bytes':0,'last_change':time.time()}
    finally: err.close()
    log(a['name']+'：开始录制')
def eligible(a):
    if not a['enabled']: return False
    if a.get('start') and datetime.now()<datetime.fromisoformat(a['start']): return False
    if a.get('end') and datetime.now()>=datetime.fromisoformat(a['end']): return False
    return True
def output_bytes(key):
    session=SESSIONS.get(key)
    if not session:return 0
    prefix=Path(session['prefix'])
    return sum(p.stat().st_size for p in prefix.parent.glob(prefix.name+'-*') if p.is_file())

def worker(key):
    wake=WAKE.setdefault(key,threading.Event());next_check=0;failures=0
    try:
        while not STOP.is_set():
            if wake.is_set():next_check=0
            wake.clear()
            with LOCK:a=next((dict(x) for x in ANCHORS if x['id']==key),None)
            if not a:break
            try:
                if not eligible(a):
                    stop_job(key)
                    STATUS[key]='录制完成' if key in SESSIONS else '暂停 / 等待计划'
                    next_check=0
                elif key in JOBS and JOBS[key].poll() is None:
                    total=output_bytes(key);health=HEALTH[key]
                    if total!=health['last_bytes']:health.update(last_bytes=total,last_change=time.time());failures=0
                    STATUS[key]='录制中' if total>1024 else '连接直播中'
                    if shutil.disk_usage(RECORD).free<1024**3:
                        stop_job(key)
                        with LOCK:
                            target=next((x for x in ANCHORS if x['id']==key),None)
                            if target:target['enabled']=False;save()
                        STATUS[key]='磁盘不足，已暂停';log(a['name']+'：磁盘不足，已暂停')
                    elif time.time()-health['last_change']>60:
                        stop_job(key);STATUS[key]='流停滞，重新连接';next_check=time.time()+5;log(a['name']+'：流停滞，重新连接')
                elif time.time()>=next_check:
                    if key in JOBS:
                        code=JOBS.pop(key).returncode
                        log(a['name']+('：录制结束，继续监控' if code==0 else '：流中断，将重新获取直播地址'))
                    STATUS[key]='检查直播';url=resolve(a)
                    with LOCK:latest=next((x for x in ANCHORS if x['id']==key),None)
                    if url and latest and eligible(latest) and not STOP.is_set():
                        start_job(latest,url);STATUS[key]='连接直播中';next_check=time.time()+5
                    else:
                        STATUS[key]='等待开播';next_check=time.time()+30;failures=0
            except Exception as e:
                failures+=1
                STATUS[key]=str(e) if isinstance(e,ValueError) else '解析失败，将自动重试'
                next_check=time.time()+min(60,5*failures)
            wake.wait(1)
    finally:stop_job(key)

def launch(a):
    WAKE.setdefault(a['id'],threading.Event())
    threading.Thread(target=worker,args=(a['id'],),daemon=True).start()

def active_recordings():
    rows=[]
    for a in ANCHORS:
        proc=JOBS.get(a['id']); session=SESSIONS.get(a['id'])
        if not proc or proc.poll() is not None or not session: continue
        prefix=Path(session['prefix'])
        files=sorted(prefix.parent.glob(prefix.name+'-*'),key=lambda p:p.stat().st_mtime,reverse=True)
        rows.append(dict(a,quality=session['quality'],estimate_mb=estimate_mb(a['mode'],session['quality']),elapsed=int(time.time()-session['started']),started=datetime.fromtimestamp(session['started']).strftime('%H:%M:%S'),bytes=sum(p.stat().st_size for p in files),segments=len(files),current_files=[str(p.relative_to(RECORD)) for p in files[:(2 if a['mode']=='both' else 1)]]))
    return rows

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self,obj,code=200):
        raw=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/api/state':
            with LOCK:
                files=[{'name':str(p.relative_to(RECORD)),'size':p.stat().st_size,'url':'/files/'+str(p.relative_to(RECORD))} for p in RECORD.rglob('*') if p.is_file()]
                self.send_json({'anchors':[dict(a,quality=a.get('quality','360'),estimate_mb=estimate_mb(a['mode'],a.get('quality','360')),status=STATUS.get(a['id'],'等待检查')) for a in ANCHORS],'proxy':proxy_service.state(),'recordings':active_recordings(),'logs':LOG,'files':files,'ffmpeg':Path(FFMPEG).exists(),'folder':str(RECORD),'desktop':{'services':desktop_controls.SERVICES}})
            return
        if self.path=='/proxy-ca.pem':
            p=proxy_service.CERT
        elif self.path=='/': p=ROOT/'index.html'
        elif self.path.startswith('/files/'):
            p=(RECORD/unquote(self.path[7:])).resolve()
            if RECORD not in p.parents: self.send_error(403); return
        else: self.send_error(404); return
        if not p.is_file(): self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length',str(p.stat().st_size)); self.send_header('Content-Type','text/html; charset=utf-8' if p.suffix=='.html' else 'application/octet-stream'); self.end_headers()
        with p.open('rb') as f: shutil.copyfileobj(f,self.wfile)
    def do_POST(self):
        # Reject cross-origin browser mutations; service listens on localhost only.
        if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
            self.send_error(403); return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': self.send_error(415); return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>65536: raise ValueError('请求过大')
            body=json.loads(self.rfile.read(size))
            with LOCK:
                if self.path=='/api/desktop/configure':
                    proxy_service.start();desktop_controls.configure('enable',str(body.get('service','')))
                elif self.path=='/api/desktop/restore':
                    desktop_controls.configure('restore')
                elif self.path=='/api/desktop/stop':
                    if (proxy_service.DIRECTORY/'system-backup.json').exists():desktop_controls.configure('restore')
                    threading.Thread(target=shutdown,daemon=True).start()
                elif self.path=='/api/rename':
                    name=str(body.get('name','')).strip()[:80]
                    if not name:raise ValueError('请输入主播名称')
                    a=next(x for x in ANCHORS if x['id']==body['id']);a['name']=name;save()
                elif self.path=='/api/proxy/start':
                    proxy_service.start(); log('视频号取流代理已启动')
                elif self.path=='/api/proxy/stop':
                    if (proxy_service.DIRECTORY/'system-backup.json').exists():raise ValueError('请先在终端运行 system_proxy.py restore 恢复系统代理，再停止取流')
                    for a in ANCHORS:
                        if a.get('capture_id'):a['enabled']=False
                    save(); proxy_service.stop(); log('取流代理已停止；请恢复系统代理设置')
                elif self.path=='/api/proxy/record':
                    item=proxy_service.source(body['id'])
                    quality=str(body.get('quality','360')); mode=body.get('mode','video')
                    if quality not in PROFILES or mode not in ('video','audio','both'):raise ValueError('录制参数无效')
                    if any(a.get('capture_room')==(item.get('room_key') or room_key(item['url'])) or a.get('capture_id')==item['id'] for a in ANCHORS):raise ValueError('此源已添加，请到主播列表开启监控')
                    a={'id':uuid.uuid4().hex,'name':str(body.get('name','视频号直播')).strip()[:80] or '视频号直播','url':'https://'+item['host']+'/（代理识别）','capture_id':item['id'],'capture_room':item.get('room_key') or room_key(item['url']),'platform':'视频号','mode':mode,'quality':quality,'enabled':True,'start':'','end':''}
                    ANCHORS.append(a);save();launch(a)
                elif self.path=='/api/shutdown':
                    if (proxy_service.DIRECTORY/'system-backup.json').exists():raise ValueError('请先恢复系统代理')
                    threading.Thread(target=shutdown,daemon=True).start()
                elif self.path=='/api/add':
                    a={'id':uuid.uuid4().hex,'name':str(body['name']).strip()[:80],'url':str(body['url']).strip(),'platform':body['platform'],'mode':body['mode'],'quality':str(body.get('quality','360')),'enabled':True,'start':body.get('start',''),'end':body.get('end','')}
                    if not a['name'] or urlparse(a['url']).scheme not in ('http','https'): raise ValueError('请输入名称和 HTTP/HTTPS 地址')
                    if a['quality'] not in PROFILES: raise ValueError('清晰度无效')
                    if a['platform'] not in ('抖音','视频号','直播流') or a['mode'] not in ('video','audio','both'): raise ValueError('录制参数无效')
                    for field in ('start','end'):
                        if a[field]: datetime.fromisoformat(a[field])
                    if a['start'] and a['end'] and a['start']>=a['end']: raise ValueError('结束时间必须晚于开始时间')
                    ANCHORS.append(a); save(); launch(a)
                elif self.path=='/api/quality':
                    quality=str(body.get('quality',''))
                    if quality not in PROFILES: raise ValueError('清晰度无效')
                    a=next(x for x in ANCHORS if x['id']==body['id']); a['quality']=quality; save()
                elif self.path=='/api/toggle':
                    a=next(x for x in ANCHORS if x['id']==body['id']); a['enabled']=not a['enabled']; save(); WAKE.setdefault(a['id'],threading.Event()).set()
                elif self.path=='/api/delete':
                    a=next(x for x in ANCHORS if x['id']==body['id']); ANCHORS.remove(a); save(); WAKE.setdefault(a['id'],threading.Event()).set()
                else: self.send_error(404); return
            self.send_json({'ok':True})
        except Exception as e: self.send_json({'error':str(e) if isinstance(e,ValueError) else '操作失败'},400)
def shutdown(*args): STOP.set(); threading.Thread(target=server.shutdown,daemon=True).start()
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    signal.signal(signal.SIGTERM,shutdown); signal.signal(signal.SIGINT,shutdown)
    if (proxy_service.DIRECTORY/'system-backup.json').exists():
        proxy_service.start();log('系统代理已配置，取流服务自动恢复')
    for a in ANCHORS:
        if a.get('capture_id') and not a.get('capture_room'):
            try:a['capture_room']=proxy_service.source(a['capture_id'])['room_key'];save()
            except ValueError:pass
        launch(a)
    print(f'直播录制工具：http://127.0.0.1:{PORT}',flush=True)
    try: server.serve_forever()
    finally:
        STOP.set()
        for key in list(JOBS): stop_job(key)
        proxy_service.stop()
        server.server_close()
