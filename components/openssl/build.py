from kiln.builders.base import AutotoolsBuild

class OpenSSLBuild(AutotoolsBuild):
    name    = "openssl"
    version = "3.2.1"
    deps    = ["zlib"]
    source  = {
        "git": "https://github.com/openssl/openssl",
        "ref": "openssl-3.2.1",
    }
    configure_args = ["no-shared", "no-tests"]
    build_weight   = 3
