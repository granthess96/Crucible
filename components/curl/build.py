from kiln.builders.base import CMakeBuild

class CurlBuild(CMakeBuild):
    name    = "curl"
    version = "8.5.0"
    deps    = ["zlib", "openssl"]
    source  = {
        "git": "https://github.com/curl/curl",
        "ref": "curl-8_5_0",
    }
    build_weight = 2