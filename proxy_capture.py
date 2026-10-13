"""mitmproxy addon: retain only live media candidates, never cookies or full flows."""
import hashlib,json,os,re,time
from pathlib import Path
from urllib.parse import urlparse
# mitmproxy script directory is not always on sys.path.
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from stream_identity import room_key
SUFFIXES=('finder.video.qq.com','findermp.video.qq.com','voipfinderliveplaythird.wxqcloud.qq.com','qpic.cn','wxapp.tc.qq.com','wxlive.qq.com','liveplay.myqcloud.com','livepull.myqcloud.com','channels.weixin.qq.com')
def allowed(host): return any(host==x or host.endswith('.'+x) for x in SUFFIXES)
def is_media(url):
    p=urlparse(url)
    return p.scheme in ('http','https') and allowed(p.hostname or '') and bool(re.search(r'\.(m3u8|flv)(?:$|[/?])',p.path,re.I))
class LiveCapture:
    def __init__(self):
        self.sources={};self.media_seen=0
        try:
            previous=json.loads(Path(os.environ['LIVE_CAPTURE_FILE']).read_text())
            for item in previous.get('sources',[]):
                if time.time()-item['seen']<1800:
                    item['room_key']=room_key(item['url']);item.setdefault('aliases',[])
                    self.sources[item['id']]=item
        except (OSError,ValueError,KeyError):pass
        self.diagnostics={'since':int(time.time()),'connects':0,'http_requests':0,'allowed_responses':0,'tls_failures':0,'related_hosts':{}}
    def running(self):
        from mitmproxy import ctx
        hosts=r'(^|\.)(finder\.video\.qq\.com|findermp\.video\.qq\.com|voipfinderliveplaythird\.wxqcloud\.qq\.com|qpic\.cn|wxapp\.tc\.qq\.com|wxlive\.qq\.com|liveplay\.myqcloud\.com|livepull\.myqcloud\.com|channels\.weixin\.qq\.com):\d+$'
        ctx.options.update(allow_hosts=[hosts])
        self.persist()
    def http_connect(self,flow):
        self.diagnostics['connects']+=1
        host=flow.request.host.lower()
        if any(host==domain or host.endswith('.'+domain) for domain in ('qq.com','qpic.cn','myqcloud.com','weixin.qq.com','wechat.com','weixin.com','wxqcloud.cn')):
            counts=self.diagnostics['related_hosts'];counts[host]=counts.get(host,0)+1
            self.diagnostics['related_hosts']=dict(list(counts.items())[-30:])
        self.persist()
    def requestheaders(self,flow):
        self.diagnostics['http_requests']+=1;self.persist()
    def tls_failed_client(self,data):
        self.diagnostics['tls_failures']+=1;self.persist()
    def remember(self,url,headers,kind,verified=False):
        parts=urlparse(url)
        if not (is_media(url) or (verified and parts.scheme in ('http','https') and allowed(parts.hostname or ''))):return
        key=hashlib.sha256(url.encode()).hexdigest()[:20]
        safe={k:headers[k] for k in ('User-Agent','Referer','Origin') if k in headers}
        room=room_key(url)
        previous=[s for s in self.sources.values() if s.get('room_key')==room]
        aliases=list(dict.fromkeys([x for s in previous for x in [s['id'],*s.get('aliases',[])]]))[-32:]
        self.sources={k:v for k,v in self.sources.items() if v.get('room_key')!=room}
        self.sources[key]={'room_key':room,'aliases':aliases,'id':key,'url':url,'headers':safe,'host':urlparse(url).hostname,'kind':kind,'seen':int(time.time())}
        self.sources={k:v for k,v in self.sources.items() if time.time()-v['seen']<1800}
        self.sources=dict(list(self.sources.items())[-50:]);self.persist()
    def persist(self):
        dest=Path(os.environ['LIVE_CAPTURE_FILE']);dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        tmp=dest.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'sources':list(self.sources.values()),'media_seen':self.media_seen,'diagnostics':self.diagnostics},f)
        tmp.replace(dest)
    def responseheaders(self,flow):
        if not allowed(flow.request.host):return
        self.diagnostics['allowed_responses']+=1;self.persist()
        content_type=flow.response.headers.get('content-type','').lower()
        # Stream media immediately; never buffer a continuous FLV response.
        if 'video/' in content_type or 'mpegurl' in content_type or is_media(flow.request.pretty_url):
            last_touch=[time.time()]
            def stream(chunk):
                if chunk and time.time()-last_touch[0]>10:
                    self.remember(flow.request.pretty_url,flow.request.headers,'HLS' if 'mpegurl' in content_type else 'FLV',verified=('flv' in content_type or 'mpegurl' in content_type))
                    last_touch[0]=time.time()
                return chunk
            flow.response.stream=stream
            self.media_seen+=1
            if 200<=flow.response.status_code<300:self.remember(flow.request.pretty_url,flow.request.headers,'HLS' if ('mpegurl' in content_type or '.m3u8' in flow.request.path) else 'FLV',verified=('flv' in content_type or 'mpegurl' in content_type))
        elif 'live' in flow.request.host and 200<=flow.response.status_code<300:
            # Forward every byte; inspect only the media magic prefix in memory.
            prefix=bytearray();checked=False;media_kind=None;last_touch=time.time()
            def identify(chunk):
                nonlocal checked,media_kind,last_touch
                if chunk and media_kind and time.time()-last_touch>10:
                    self.remember(flow.request.pretty_url,flow.request.headers,media_kind,verified=True);last_touch=time.time()
                if not checked and chunk:
                    prefix.extend(chunk[:max(0,16-len(prefix))])
                    if len(prefix)>=7:
                        checked=True
                        kind='FLV' if prefix.startswith(b'FLV') else 'HLS' if prefix.startswith(b'#EXTM3U') else None
                        if kind:
                            media_kind=kind
                            self.media_seen+=1;self.remember(flow.request.pretty_url,flow.request.headers,kind,verified=True)
                        prefix.clear()
                return chunk
            flow.response.stream=identify
        elif 'json' not in content_type or not re.search(r'live|finder',flow.request.path,re.I):
            flow.response.stream=True
    def response(self,flow):
        if not allowed(flow.request.host) or flow.response.stream:return
        body=flow.response.raw_content or b''
        if len(body)>1048576:return
        try: data=json.loads(flow.response.get_text())
        except Exception:return
        def visit(value,depth=0):
            if depth>12:return
            if isinstance(value,dict):
                for k,v in value.items():
                    # Only inspect live/stream/url related metadata; do not persist response bodies.
                    if isinstance(v,(dict,list)) or re.search(r'url|stream|play|live',k,re.I):visit(v,depth+1)
            elif isinstance(value,list):
                for v in value[:200]:visit(v,depth+1)
            elif isinstance(value,str) and is_media(value):self.remember(value,flow.request.headers,'候选直播流')
        visit(data)
addons=[LiveCapture()]
