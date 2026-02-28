from kiln.builders.base import CMakeBuild

class ZlibBuild(CMakeBuild):
    name    = "zlib"
    version = "1.3.1"
    cmake_generator = 'Unix Makefiles'
    deps    = []
    source  = {
        "git": "https://github.com/madler/zlib",
        "ref": "v1.3.1",
    }
    configure_args = ["-DCMAKE_BUILD_TYPE=Release"]
