# components/rsync/build.py
from kiln.builders import AutotoolsBuild
from kiln.spec import FileSpec

class Rsync(AutotoolsBuild):
    name    = 'rsync'
    version = '3.4.1'
    deps    = ['zlib', 'openssl', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://download.samba.org/pub/rsync/rsync-3.4.1.tar.gz',
    }
    configure_args = [
        '--disable-xxhash',
        '--disable-zstd',
        '--disable-lz4',
        '--without-included-zlib',
        '--with-openssl',
        '--without-popt',   # use bundled mini-popt
    ]

    files = [
        FileSpec("usr/bin/**", role="tool"),
    ]
