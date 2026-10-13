import json,shlex,subprocess,sys
from pathlib import Path
from runtime_paths import DATA,ASSETS
try:
 SERVICES=[s for s in subprocess.check_output(['/usr/sbin/networksetup','-listallnetworkservices'],text=True).splitlines()[1:] if s and not s.startswith('*')]
except Exception:SERVICES=[]
def configure(action,service=''):
 if action=='enable' and service not in SERVICES:raise ValueError('请选择当前使用的网络服务')
 if getattr(sys,'frozen',False):args=[sys.executable,'--data-root',str(DATA),'--system-proxy',action]
 else:args=[sys.executable,str(ASSETS/'system_proxy.py'),action]
 if service:args.append(service)
 script='do shell script '+json.dumps(shlex.join(args),ensure_ascii=False)+' with administrator privileges'
 result=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,text=True,timeout=180)
 if result.returncode:raise ValueError('未完成系统配置：授权可能已取消。请重试，或检查系统网络设置。')
