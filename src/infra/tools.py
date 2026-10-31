"""Install versioned upstream binaries locally, verifying release checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import tarfile
import tempfile

from src.infra.common import STATE, TOOLS, VERSIONS, run


def platform_pair():
    system = platform.system().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if system not in ("darwin", "linux") or arch is None:
        raise RuntimeError("Supported tool platforms: macOS/Linux on arm64/amd64")
    return system, arch


def download(url, destination):
    # curl uses the platform trust store and fails on non-2xx responses.
    run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "20",
         "--max-time", "600", "--output", destination, url])


def verify_checksum(path, expected):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Invalid SHA-256 checksum")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"SHA-256 mismatch: {path.name}")


def install(name, url, checksum_url, member=None):
    destination = TOOLS / "bin" / name
    stamp = TOOLS / "versions" / name
    version = VERSIONS["substrate" if name == "kubectl-ate" else name]
    if destination.exists() and stamp.exists() and stamp.read_text().strip() == version:
        print(f"OK {name} {version}")
        return
    with tempfile.TemporaryDirectory(dir=TOOLS) as tmp:
        archive = Path(tmp) / "download"
        checksum = Path(tmp) / "checksum"
        download(url, archive)
        download(checksum_url, checksum)
        expected = checksum.read_text().split()[0]
        verify_checksum(archive, expected)
        if member:
            with tarfile.open(archive) as tar:
                stream = tar.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"Missing archive member {member}")
                with destination.open("wb") as output:
                    shutil.copyfileobj(stream, output)
        else:
            shutil.copyfile(archive, destination)
        destination.chmod(0o755)
        stamp.write_text(version + "\n")


def install_go(system, arch):
    version = VERSIONS["go"]
    target = TOOLS / version
    link = TOOLS / "bin/go"
    if (target / "bin/go").exists():
        if link.is_symlink():
            link.unlink()
        if link.exists():
            raise RuntimeError("Refusing to replace a non-symlink Go binary in .tools/bin")
        link.symlink_to(target / "bin/go")
        return
    with tempfile.TemporaryDirectory(dir=TOOLS) as tmp:
        index = Path(tmp) / "go.json"
        download("https://go.dev/dl/?mode=json&include=all", index)
        filename = f"{version}.{system}-{arch}.tar.gz"
        files = [f for release in json.loads(index.read_text()) if release["version"] == version
                 for f in release["files"] if f["filename"] == filename]
        if len(files) != 1:
            raise RuntimeError(f"No release checksum for {filename}")
        archive = Path(tmp) / filename
        download(f"https://go.dev/dl/{filename}", archive)
        verify_checksum(archive, files[0]["sha256"])
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        shutil.move(str(Path(tmp) / "go"), target)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target / "bin/go")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-go", action="store_true", help="Also install the Substrate installer toolchain")
    args = parser.parse_args()
    for path in (TOOLS / "bin", TOOLS / "versions", STATE):
        path.mkdir(parents=True, exist_ok=True)
    system, arch = platform_pair()
    base = "https://github.com/kubernetes-sigs/kind/releases/download/" + VERSIONS["kind"]
    install("kind", f"{base}/kind-{system}-{arch}", f"{base}/kind-{system}-{arch}.sha256sum")
    base = f"https://dl.k8s.io/release/{VERSIONS['kubectl']}/bin/{system}/{arch}/kubectl"
    install("kubectl", base, base + ".sha256")
    base = f"https://get.helm.sh/helm-{VERSIONS['helm']}-{system}-{arch}.tar.gz"
    install("helm", base, base + ".sha256sum", member=f"{system}-{arch}/helm")
    base = f"https://github.com/agent-substrate/substrate/releases/download/{VERSIONS['substrate']}/kubectl-ate-{system}-{arch}"
    install("kubectl-ate", base, base + ".sha256")
    if args.with_go:
        install_go(system, arch)
    print(f"Tools installed in {TOOLS / 'bin'}; scripts prepend this directory automatically.")


if __name__ == "__main__":
    main()
