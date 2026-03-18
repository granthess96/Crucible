from kiln.builders import ImageDef, BuildPaths

class BaseImage(ImageDef):
    name    = 'base-image'
    version = '1.0'
    deps    = [
        'bash',
        'bzip2',
        'cmake',
        'coreutils',
        'findutils',
        'gawk',
        'glibc',
        'grep',
        'gzip',
        'linux-headers',
        'm4',
        'make',
        'flex',
        'bison',
        'openssl',
        'perl',
        'python3',
        'patch',
        'ncurses',
        'readline',
        'sed',
        'tar',
        'xz',
        'zlib'
    ]
    source  = {}   # no upstream source — pure assembly, Option C TODO

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        return []

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []
