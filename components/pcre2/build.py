from kiln.builders import CMakeBuild

class PCRE2(CMakeBuild):
    name    = 'pcre2'
    version = '10.47'
    deps    = ['glibc', 'linux-headers', 'zlib']
    source  = {
        'git': 'https://github.com/PCRE2Project/pcre2',
        'ref': 'pcre2-10.47',
    }
    configure_args = [
        '-DCMAKE_INSTALL_PREFIX=/usr',
        '-DPCRE2_BUILD_PCRE2_8=ON',
        '-DPCRE2_BUILD_PCRE2_16=ON',
        '-DPCRE2_BUILD_PCRE2_32=ON',
        '-DPCRE2_SUPPORT_UNICODE=ON',
        '-DPCRE2_BUILD_TESTS=OFF',
        '-DZLIB_ROOT={sysroot}/usr',
    ]
