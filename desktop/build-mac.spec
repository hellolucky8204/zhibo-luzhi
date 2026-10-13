from PyInstaller.utils.hooks import collect_all
from pathlib import Path
root=Path(SPECPATH)
import sys
proxy_packages=root.parents[1]/"work/proxy-venv/lib/python3.12/site-packages"
if proxy_packages.exists():sys.path.insert(0,str(proxy_packages))
datas=[(str(root/name),'.') for name in ('app.py','proxy_service.py','proxy_capture.py','stream_identity.py','system_proxy.py','index.html','desktop_controls.py')]
binaries=[];hidden=['runtime_paths','desktop_controls','proxy_service','stream_identity','streamget.platforms.douyin.live_stream','mitmproxy.tools.main']
for package in ('streamget','mitmproxy'):
 d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
binaries += [(str(root/'bin/ffmpeg'),'bin'),(str(root/'bin/node'),'bin')]
a=Analysis([str(root/'desktop_launcher.py')],pathex=[str(root),str(proxy_packages)],binaries=binaries,datas=datas,hiddenimports=hidden,hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['faster_whisper','torch','onnxruntime'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='直播录制工作台',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='直播录制工作台')
app=BUNDLE(coll,name='直播录制工作台.app',bundle_identifier='com.zhiboluzhi.recorder',info_plist={'CFBundleDisplayName':'直播录制工作台','NSHighResolutionCapable':True})
