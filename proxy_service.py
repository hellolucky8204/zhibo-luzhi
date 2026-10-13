import json,os,shutil,socket,subprocess,time
from pathlib import Path
from stream_identity import choose_source,room_key
ROOT=Path(__file__).resolve().parent
DIRECTORY=ROOT/'data'/'proxy'; DIRECTORY.mkdir(parents=True,exist_ok=True,mode=0o700)
SOURCES=DIRECTORY/'sources.json'; CERT=DIRECTORY/'ca'/'mitmproxy-ca-cert.pem'
PROXY_PORT=8899
PROCESS=None

def binary():
    return shutil.which('mitmdump') or str(ROOT/'.venv/bin/mitmdump')
def state():
    global PROCESS
    active=PROCESS is not None and PROCESS.poll() is None
    items=[];count=0
    if active and SOURCES.exists():
        try:
            payload=json.loads(SOURCES.read_text());count=payload.get('media_seen',0)
            items=[{k:v for k,v in s.items() if k not in ('url','headers')} for s in payload['sources'] if time.time()-s['seen']<1800]
        except Exception:pass
    return {'running':active,'port':PROXY_PORT,'cert_ready':CERT.exists(),'sources':items,'media_seen':count,'system_configured':(DIRECTORY/'system-backup.json').exists(),'diagnostics':payload.get('diagnostics',{}) if active and SOURCES.exists() and 'payload' in locals() else {}}
def start():
    global PROCESS
    if PROCESS is not None and PROCESS.poll() is None:return
    if not Path(binary()).is_file():raise ValueError('代理依赖未安装')
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',PROXY_PORT))
        except OSError:raise ValueError('8899 端口已占用，不能启动取流代理')
    if not SOURCES.exists():SOURCES.write_text('{"sources":[],"media_seen":0}')
    SOURCES.chmod(0o600)
    ca=DIRECTORY/'ca';ca.mkdir(mode=0o700,exist_ok=True)
    env=dict(os.environ,LIVE_CAPTURE_FILE=str(SOURCES))
    hosts=r'(^|\.)(finder\.video\.qq\.com|findermp\.video\.qq\.com|voipfinderliveplaythird\.wxqcloud\.qq\.com|qpic\.cn|wxapp\.tc\.qq\.com|wxlive\.qq\.com|liveplay\.myqcloud\.com|livepull\.myqcloud\.com|channels\.weixin\.qq\.com):\d+$'
    PROCESS=subprocess.Popen([binary(),'-q','--listen-host','127.0.0.1','--listen-port',str(PROXY_PORT),'--set','confdir='+str(ca),'--set','flow_detail=0','--set','stream_large_bodies=1m','--allow-hosts',hosts,'-s',str(ROOT/'proxy_capture.py')],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(200):
        if PROCESS.poll() is not None:raise ValueError('代理启动失败，请检查依赖')
        try:
            with socket.create_connection(('127.0.0.1',PROXY_PORT),timeout=.2):return
        except OSError:time.sleep(.1)
    stop();raise ValueError('代理启动超时')
def stop():
    global PROCESS
    if PROCESS and PROCESS.poll() is None:
        PROCESS.terminate()
        try:PROCESS.wait(timeout=8)
        except subprocess.TimeoutExpired:PROCESS.kill();PROCESS.wait()
    PROCESS=None
    if SOURCES.exists():SOURCES.write_text('{"sources":[],"media_seen":0}')
def source(key):
    if not state()['running']:raise ValueError('请先启动取流代理')
    rows=json.loads(SOURCES.read_text()).get('sources',[])
    for s in rows:s.setdefault('room_key',room_key(s['url']))
    item=choose_source(rows,key,time.time())
    if not item:raise ValueError('等待此直播的新地址；保持微信播放，或重新打开此直播')
    return item
