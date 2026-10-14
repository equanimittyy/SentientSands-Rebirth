import struct

from core.paths import resolve_mod_file


def read_mod_version(path):
    with open(path, "rb") as f:
        header = f.read(12)
    # FCS writes file type 17: the type, the size of the header, then the version that FCS sets
    return struct.unpack_from("<i", header, 8)[0]


MOD_VERSION = read_mod_version(resolve_mod_file("SentientSandsRebirth.mod"))
