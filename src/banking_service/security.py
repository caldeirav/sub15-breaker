"""Check the current process using syscalls, without relying on procfs ownership."""
import ctypes
import os
import stat


def normalize_guest_root():
    root=os.stat("/")
    if stat.S_IMODE(root.st_mode)==0o700 and root.st_uid==0:
        # The pinned runtime creates a private overlay upper root with 0700.
        # Restore the banking image's public read/execute root before setuid;
        # never recurse or modify a host path or shared image-cache directory.
        os.chmod("/",0o555)
    elif stat.S_IMODE(root.st_mode) not in {0o555,0o755}:
        raise RuntimeError("Unexpected guest root permissions")


def identity():
    class Header(ctypes.Structure):
        _fields_=[("version",ctypes.c_uint32),("pid",ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_=[("effective",ctypes.c_uint32),("permitted",ctypes.c_uint32),("inheritable",ctypes.c_uint32)]
    libc=ctypes.CDLL(None,use_errno=True)
    header,data=Header(0x20080522,0),(Data*2)()
    if libc.capget(ctypes.byref(header),ctypes.byref(data))!=0:raise RuntimeError("Cannot inspect process capabilities")
    no_new_privs=libc.prctl(39,0,0,0,0)
    if no_new_privs<0:raise RuntimeError("Cannot inspect no_new_privs")
    return dict(uid=os.geteuid(),gid=os.getegid(),effective_capabilities=f"{data[0].effective | (data[1].effective<<32):016x}",
                no_new_privs=str(no_new_privs))


def drop_privileges():
    if os.geteuid()==0:
        normalize_guest_root()
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0:raise RuntimeError("Cannot set no_new_privs")
    info=identity()
    if info["uid"]!=10001 or info["gid"]!=10001 or int(info["effective_capabilities"],16)!=0:
        raise RuntimeError("Runtime identity/capability requirements are not satisfied")
