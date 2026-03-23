from kiln.builders import ImageDef, BuildPaths

class BaseImage(ImageDef):
    name    = 'base-image'
    version = '1.0'
    deps    = [
        'bash',
        'bzip2',
        'cmake',
        'coreutils',
        'filesystem',
        'findutils',
        'gawk',
        'glibc',
        'grep',
        'gzip',
        'linux-headers',
        'm4',
        'make',
        'ninja',
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

    def post_install(self, rootfs: Path) -> None:
        # FHS compatibility — /bin, /sbin, /lib, /lib64 → usr equivalents
        for link in ('bin', 'sbin', 'lib', 'lib64'):
            target = rootfs / link
            if not target.exists():
                target.symlink_to(f'usr/{link}')
