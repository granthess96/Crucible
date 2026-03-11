# components/curl/build.py
from kiln.builders.base import CMakeBuild

class CurlBuild(CMakeBuild):
    name    = 'curl'
    version = '8.11.1'
    deps    = ['zlib', 'openssl']
    build_weight = 2
    source  = {
        'url': 'https://curl.se/download/curl-8.11.1.tar.xz',
    }