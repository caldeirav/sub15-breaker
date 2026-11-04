"""Build transport controls are explicit; a failed build never publishes an image."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("dns",[None,"192.0.2.53"])
def test_build_dns_opt_in_and_bounded_downloads_preserve_failure(tmp_path,dns):
    scripts=tmp_path/"scripts";scripts.mkdir()
    script=scripts/"build_banking_image.sh"
    script.write_text((ROOT/"scripts/build_banking_image.sh").read_text())
    tools=tmp_path/".tools/bin";tools.mkdir(parents=True)
    (tools/"uv").write_text("#!/bin/sh\nexit 0\n")
    podman=tools/"podman"
    podman.write_text("#!/usr/bin/env python3\n"+'''
import json,os,sys
with open(os.environ["COMMAND_LOG"],"a") as stream:stream.write(json.dumps(sys.argv[1:])+"\\n")
if sys.argv[1]=="inspect":print("banking-03b")
if sys.argv[1]=="build":sys.exit(42)
''')
    for path in (tools/"uv",podman):path.chmod(0o700)
    env=dict(os.environ,COMMAND_LOG=str(tmp_path/"commands.jsonl"))
    for key in ("BANKING_BUILD_DNS","UV_CONCURRENT_DOWNLOADS","UV_HTTP_RETRIES","UV_HTTP_TIMEOUT"):
        env.pop(key,None)
    if dns:env["BANKING_BUILD_DNS"]=dns
    result=subprocess.run(["bash",str(script)],env=env,capture_output=True,text=True)
    assert result.returncode==1 and "no new image was published or deployed" in result.stderr
    calls=[json.loads(line) for line in (tmp_path/"commands.jsonl").read_text().splitlines()]
    build=next(c for c in calls if c[0]=="build")
    assert "UV_CONCURRENT_DOWNLOADS=4" in build and "UV_HTTP_RETRIES=5" in build
    assert "UV_HTTP_TIMEOUT=60" in build
    assert ("--dns" in build)==bool(dns)
    if dns:assert build[build.index("--dns")+1]==dns
    assert not any(c[0] in {"push","exec","run"} for c in calls)


def test_image_transport_settings_do_not_weaken_locked_install_or_runtime():
    text=(ROOT/"Dockerfile.banking").read_text()
    build,final=text.split("\nFROM ",1)
    assert "--locked --only-group banking-service" in build
    assert "UV_CONCURRENT_DOWNLOADS" in build and "UV_HTTP_RETRIES" in build
    assert "UV_HTTP_RETRIES" not in final and "USER 10001:10001" in final
    assert "--native-tls=false" not in text and "--allow-insecure-host" not in text
