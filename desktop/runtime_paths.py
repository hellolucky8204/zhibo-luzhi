import os,sys
from pathlib import Path
ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
DATA=Path(os.environ.get('LIVE_RECORDER_DATA',str(Path.home()/'Library/Application Support/直播录制工作台')))
DATA.mkdir(parents=True,exist_ok=True)
RECORDINGS=Path(os.environ.get('LIVE_RECORDER_RECORDINGS',str(Path.home()/'Movies/直播录制')))
RECORDINGS.mkdir(parents=True,exist_ok=True)
BIN=ASSETS/'bin'
os.environ['PATH']=str(BIN)+os.pathsep+os.environ.get('PATH','')
