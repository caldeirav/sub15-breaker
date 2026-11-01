"""Drop the pinned Actor runtime's initial identity before importing the service."""
from pathlib import Path
from src.banking_service.security import drop_privileges


def main():
    # gVisor can deny reopening /proc/self after a UID transition. Read this
    # process's mount inventory through an already-open, read-only descriptor,
    # then close it before importing or serving the application.
    with Path("/proc/self/mountinfo").open() as mounts:
        drop_privileges()
        inventory=[line.split()[4] for line in mounts.read().splitlines()]
    from src.banking_service.app import main as serve
    serve(runtime_mounts=inventory)


if __name__=="__main__":main()
