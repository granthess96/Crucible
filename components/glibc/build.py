from kiln.builders.base import AutotoolsBuild

class GlibcBuild(AutotoolsBuild):
    name    = "glibc"
    version = "2.42"
    deps    = ['linux-headers']
    source  = {
        "git": "https://sourceware.org/git/glibc.git",
        "ref": "glibc-2.42",
    }
