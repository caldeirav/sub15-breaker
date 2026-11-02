"""Run the explicit offline UI fixture in a real browser, never the live runtime."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    if not os.getenv("PLAYWRIGHT_MODULE"):
        raise RuntimeError("Set PLAYWRIGHT_MODULE to an external Playwright index.mjs; no app dependency is installed implicitly.")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",8092))
    output=ROOT/".infra"/("ui-browser-offline-"+uuid4().hex)
    output.mkdir(mode=0o700)
    with (output/"server.log").open("w") as log:
        process=subprocess.Popen([sys.executable,"-m","validation.live_ui_fixture_server","--directory",str(output/"fixture"),"--port","8092"],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+30
            while True:
                if process.poll() is not None:raise RuntimeError("Fixture server exited; inspect its private log.")
                try:
                    with urlopen("http://127.0.0.1:8092/",timeout=1) as response:
                        if response.status==200:break
                except OSError:pass
                if time.monotonic()>deadline:raise RuntimeError("Fixture startup deadline")
                time.sleep(.1)
            subprocess.run(["node","validation/check_live_ui.mjs","--url","http://127.0.0.1:8092","--output",str(output/"browser")],cwd=ROOT,check=True,timeout=120)
            print(output)
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__=="__main__":main()
