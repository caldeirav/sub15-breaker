"""HTTP fixture client; credentials come from a local Kubernetes test Secret."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request


def request(url, body, auth="valid", method="POST", content_type="application/json", spoof=False):
    headers = {"content-type": content_type}
    if auth != "none":
        headers["authorization"] = "Bearer " + (os.environ["FIXTURE_TOKEN"] if auth == "valid" else "invalid")
    if spoof:
        headers["x-breaker-grant"] = "forged-client-grant"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return dict(status=response.status, body=response.read().decode())
    except urllib.error.HTTPError as exc:
        return dict(status=exc.code, body=exc.read().decode())


if __name__ == "__main__":
    print(json.dumps(request(sys.argv[1], base64.b64decode(sys.argv[2]), *sys.argv[3:])))
