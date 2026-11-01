#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.tools/bin:$PATH"
export KIND_EXPERIMENTAL_PROVIDER=podman
uv run --locked python -c 'from src.infra.manage import Cluster; Cluster("breaker-substrate").ensure_owned()'
registry_image='docker.io/library/registry@sha256:6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e'
if podman container exists kind-registry; then
  owner="$(podman inspect --format '{{index .Config.Labels "io.sub15-breaker.owner"}}' kind-registry)"
  if [[ "$owner" != banking-03b ]]; then
    echo 'Refusing to adopt an unrelated kind-registry container' >&2
    exit 1
  fi
  podman start kind-registry >/dev/null
else
  podman run -d --name kind-registry --label io.sub15-breaker.owner=banking-03b \
    --network kind -p 127.0.0.1:5002:5000 "$registry_image"
fi
mkdir -p .infra/banking-service-03b
podman build -f Dockerfile.banking -t localhost/breaker-banking:03b .
podman run --rm --network none --workdir / --entrypoint python localhost/breaker-banking:03b \
  -c 'import os; import src.banking_service.app; assert os.getuid() == 10001'
podman run --rm --network none --user 0 --cap-drop ALL --cap-add SETUID --cap-add SETGID \
  --workdir / --entrypoint python localhost/breaker-banking:03b \
  -c 'import os; os.chmod("/", 0o700); from src.banking_service.entrypoint import drop_privileges; drop_privileges(); import src.banking_service.app'
podman push --tls-verify=false --digestfile .infra/banking-service-03b/image.digest \
  localhost/breaker-banking:03b localhost:5002/breaker-banking:03b
digest="$(cat .infra/banking-service-03b/image.digest)"
if [[ ! "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo 'Invalid registry digest' >&2
  exit 1
fi
while IFS= read -r node; do
  podman exec "$node" ctr --namespace k8s.io images pull --plain-http "kind-registry:5000/breaker-banking@$digest"
  podman exec "$node" ctr --namespace k8s.io images tag --force \
    "kind-registry:5000/breaker-banking@$digest" "localhost:5002/breaker-banking@$digest"
done < <(kind get nodes --name breaker-substrate)
printf '%s\n' "localhost:5002/breaker-banking@$digest" > .infra/banking-service-03b/image.reference
echo "Banking image: localhost:5002/breaker-banking@$digest"
