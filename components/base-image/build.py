from kiln.builders.base import ImageDef, BuildPaths

class BaseImage(ImageDef):
    name    = 'base-image'
    version = '1.0'
    deps    = [
        'linux-headers',
        'glibc',
        'zlib',
        'ncurses',
        'readline',
        'bash',
        'coreutils',
        'sed',
        'grep',
        'gawk',
        'findutils',
        'pcre2',
        'tar',
        'xz',
        'curl',
        'libpng',
        'gzip',
        'bzip2',
        'make'
#        'perl',
#        'm4',
#        'autoconf',
#        'automake',
#        'bison',
#        'gperf',
#        'gettext',
#        'help2man',
#        'texinfo',
#        'patch',
#        'diffutils',
    ]
    source  = {}   # no upstream source — pure assembly, Option C TODO

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        return []

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []
