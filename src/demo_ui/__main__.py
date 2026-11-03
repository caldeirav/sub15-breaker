"""Serve the local live demo UI; no cases execute until an authenticated Run click."""
import argparse
import os
from pathlib import Path
import secrets

import uvicorn

from src.demo_ui.protocol import BASE,ROOT,make_plan
from src.demo_ui.app import create_app
from src.demo_ui.runtime import Runtime
from src.demo_ui.state import Controller


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact",type=Path,default=BASE/"modernbert-training-v1/model")
    parser.add_argument("--port",type=int,default=8091)
    args=parser.parse_args()
    if not 1024<=args.port<=65535 or args.port in {1234,5001,8172,8173}:parser.error("choose a distinct loopback UI port")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0";os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    directory=ROOT/".infra/live-demo-ui";directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    token_path=directory/"ui.token"
    if not token_path.exists():
        fd=os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as stream:stream.write(secrets.token_urlsafe(32))
    if token_path.is_symlink() or token_path.stat().st_uid!=os.getuid() or token_path.stat().st_mode&0o077:
        raise ValueError("ui_token_must_be_a_private_owned_file")
    controller=Controller(make_plan(args.artifact),directory,
        lambda plan,usage,path:Runtime(plan,usage,path,args.artifact))
    print(f"Live demo: http://127.0.0.1:{args.port}; enter the separate UI run token from {token_path}",flush=True)
    print("Repeatable demo: no allocations or budgets. Explicit Run clicks execute fresh pairs; Gemini charges still apply. Ctrl-C waits for active work and restores the native hook.",flush=True)
    uvicorn.run(create_app(controller,token_path.read_text().strip(),port=args.port),host="127.0.0.1",port=args.port,
                access_log=False,timeout_graceful_shutdown=8100)


if __name__=="__main__":main()
