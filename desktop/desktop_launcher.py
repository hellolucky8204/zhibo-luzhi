import os,sys,runpy,socket,webbrowser,threading,time
from pathlib import Path
if '--data-root' in sys.argv:
 i=sys.argv.index('--data-root');os.environ['LIVE_RECORDER_DATA']=sys.argv[i+1];del sys.argv[i:i+2]
import runtime_paths
if len(sys.argv)>1 and sys.argv[1]=='--self-test':
 import subprocess,json
 import streamget
 from mitmproxy.tools.main import mitmdump
 for name in ('ffmpeg','node'):
  result=subprocess.run([str(runtime_paths.BIN/name),'-version' if name=='ffmpeg' else '--version'],capture_output=True,timeout=15)
  if result.returncode:raise RuntimeError(name+'运行失败')
 print(json.dumps({'runtime':True,'streamget':True,'proxy':True,'binaries':True}))
 sys.exit(0)
elif len(sys.argv)>1 and sys.argv[1]=='--proxy':
 sys.argv.pop(1)
 from mitmproxy.tools.main import mitmdump
 mitmdump()
elif len(sys.argv)>1 and sys.argv[1]=='--system-proxy':
 sys.argv.pop(1);runpy.run_path(str(runtime_paths.ASSETS/'system_proxy.py'),run_name='__main__')
else:
 # Separate port from the development recorder; never replace an active service.
 port=8870
 for candidate in range(8870,8890):
  with socket.socket() as sock:
   try:sock.bind(('127.0.0.1',candidate));port=candidate;break
   except OSError:continue
 else:raise RuntimeError('本地服务端口被占用，请关闭之前的录制应用后重试。')
 sys.argv=[str(runtime_paths.ASSETS/'app.py'),str(port)]
 def show():
  for _ in range(100):
   try:
    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
   except OSError:time.sleep(.1)
  webbrowser.open(f'http://127.0.0.1:{port}')
 if os.environ.get('LIVE_RECORDER_HEADLESS')!='1':threading.Thread(target=show,daemon=True).start()
 runpy.run_path(str(runtime_paths.ASSETS/'app.py'),run_name='__main__')
