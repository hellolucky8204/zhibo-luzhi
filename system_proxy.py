"""Run in the user's Terminal with sudo. Snapshot and restore only the selected network service."""
import hashlib,json,os,re,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BACKUP=ROOT/'data/proxy/system-backup.json'
CERT=ROOT/'data/proxy/ca/mitmproxy-ca-cert.pem'
KEYCHAIN='/Library/Keychains/System.keychain'
NET='/usr/sbin/networksetup';SEC='/usr/bin/security'
def run(*args):return subprocess.run(list(args),check=True,capture_output=True,text=True).stdout

def parse_proxy(text):
    fields=dict(line.split(': ',1) for line in text.splitlines() if ': ' in line)
    if fields.get('Authenticated Proxy Enabled')=='1':raise RuntimeError('原代理带有身份验证，无法可靠恢复密码；请改用手动配置。')
    return {'enabled':fields.get('Enabled')=='Yes','server':fields.get('Server',''),'port':int(fields.get('Port','0'))}
def restore_proxy(service,kind,state):
    if state['server'] and state['port']:run(NET,'-set'+kind+'proxy',service,state['server'],str(state['port']))
    elif not state['enabled']:run(NET,'-set'+kind+'proxy',service,'', '0')
    run(NET,'-set'+kind+'proxystate',service,'on' if state['enabled'] else 'off')
def remove_cert():
    run(SEC,'remove-trusted-cert','-d',str(CERT))
    raw=subprocess.check_output(['/usr/bin/openssl','x509','-in',str(CERT),'-outform','DER'])
    fingerprint=hashlib.sha1(raw).hexdigest().upper()
    run(SEC,'delete-certificate','-Z',fingerprint,KEYCHAIN)
def restore():
    if not BACKUP.exists():raise RuntimeError('没有本工具的代理备份，未修改任何设置。')
    data=json.loads(BACKUP.read_text())
    for kind in ('web','secureweb'):restore_proxy(data['service'],kind,data[kind])
    if data.get('cert_added'):remove_cert()
    BACKUP.unlink();print('已恢复原 HTTP / HTTPS 代理，并移除本工具安装的证书。')
def enable():
    if BACKUP.exists():raise RuntimeError('已有配置备份。请先运行 restore，避免覆盖原设置。')
    if not CERT.exists():raise RuntimeError('请先在工作台启动取流代理。')
    with socket.create_connection(('127.0.0.1',8899),timeout=2):pass
    services=[s for s in run(NET,'-listallnetworkservices').splitlines()[1:] if s and not s.startswith('*')]
    for i,name in enumerate(services,1):print(str(i)+'. '+name)
    selection=int(input('选择当前连接网络的服务编号（通常是 Wi-Fi）：'))
    if not 1<=selection<=len(services):raise RuntimeError('编号无效')
    service=services[selection-1]
    data={'service':service,'cert_added':False}
    for kind in ('web','secureweb'):data[kind]=parse_proxy(run(NET,'-get'+kind+'proxy',service))
    # Never install or later remove an existing copy of this certificate.
    der=subprocess.check_output(['/usr/bin/openssl','x509','-in',str(CERT),'-outform','DER']);fp=hashlib.sha1(der).hexdigest().upper()
    existing=run(SEC,'find-certificate','-a','-Z',KEYCHAIN)
    if fp in existing:raise RuntimeError('此证书已在系统钥匙串，未继续自动配置；请手动检查信任和代理。')
    BACKUP.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(BACKUP,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f)
    try:
        run(SEC,'add-trusted-cert','-d','-r','trustRoot','-k',KEYCHAIN,str(CERT))
        data['cert_added']=True;BACKUP.write_text(json.dumps(data))
        for kind in ('web','secureweb'):
            run(NET,'-set'+kind+'proxy',service,'127.0.0.1','8899')
            run(NET,'-set'+kind+'proxystate',service,'on')
    except Exception:
        print('配置未完成，尝试恢复原设置。')
        restore();raise
    print('配置完成。请在电脑微信重新打开视频号直播，并查看工作台候选源。')
    print('结束时先执行 restore，再停止取流代理；系统代理开启期间保持代理服务运行。')
if __name__=='__main__':
    if sys.platform!='darwin':sys.exit('本配置脚本仅支持 macOS。')
    if os.geteuid()!=0:sys.exit('需要在你自己的终端使用 sudo 执行，管理员密码只输入在终端。')
    try:
        action=sys.argv[1] if len(sys.argv)>1 else ''
        if action=='enable':enable()
        elif action=='restore':restore()
        else:sys.exit('用法：system_proxy.py enable 或 restore')
    except Exception as e:sys.exit('操作未完成：'+str(e))
