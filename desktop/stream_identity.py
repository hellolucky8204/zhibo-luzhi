"""Live-session identity excludes temporary credentials; it is not a cross-session account ID."""
import hashlib,re
from urllib.parse import urlparse,parse_qs

def room_key(url):
    parts=urlparse(url);params=parse_qs(parts.query)
    for field in ('stream_id','streamid','room_id','roomid','live_id','liveid'):
        if params.get(field):return hashlib.sha256(('wechat:'+field+':'+params[field][0]).encode()).hexdigest()[:20]
    # Actual observed WeChat FLV paths carry the live stream identity.
    path=re.sub(r'\.(flv|m3u8)$','',parts.path,flags=re.I)
    return hashlib.sha256(('wechat:'+path).encode()).hexdigest()[:20]

def choose_source(rows,key,now):
    matches=[s for s in rows if (s.get('room_key')==key or s['id']==key or key in s.get('aliases',[])) and now-s['seen']<1800]
    return max(matches,key=lambda s:s['seen']) if matches else None
