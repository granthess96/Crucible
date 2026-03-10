from kiln.builders.base import AutotoolsBuild, BuildPaths

class NcursesBuild(AutotoolsBuild):
    name    = "ncurses"
    version = "6.4"
    deps    = ['glibc']
    source  = {
        "git": "https://github.com/mirror/ncurses.git",
        "ref": "v6.4",
    }
    
    configure_args = ['--prefix=/usr', 
                        '--with-shared',
                        '--enable-widec', 
                        '--with-cxx-binding',
                        '--with-cxx-shared',
                        '--without-ada',
                        '--enable-pc-files',
                        '--with-pkg-config-libdir=/usr/lib/pkgconfig',
                        '--with-cxx-main',
                        '--disable-db-install'
                      ]
    
    comp_flags = ['-O2', '-std=c++17', '-std=gnu17']
    link_flags = []

