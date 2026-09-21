use std::{env, fs, path::PathBuf};

fn main() {
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let source = PathBuf::from("vendor/oniguruma/src");
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    let width = env::var("CARGO_CFG_TARGET_POINTER_WIDTH").unwrap();
    if os == "windows" {
        let config = if width == "64" {
            "config.h.win64"
        } else {
            "config.h.win32"
        };
        fs::copy(source.join(config), out.join("config.h")).unwrap();
    } else {
        let bytes = if width == "64" { 8 } else { 4 };
        fs::write(
            out.join("config.h"),
            format!(
                "#define HAVE_STDINT_H 1\n#define HAVE_INTTYPES_H 1\n\
             #define HAVE_SYS_TYPES_H 1\n#define HAVE_SYS_TIME_H 1\n\
             #define HAVE_UNISTD_H 1\n#define HAVE_ALLOCA_H 1\n\
             #define HAVE_ALLOCA 1\n#define SIZEOF_INT 4\n\
             #define SIZEOF_LONG {bytes}\n#define SIZEOF_LONG_LONG 8\n\
             #define SIZEOF_VOIDP {bytes}\n#define SIZEOF_SIZE_T {bytes}\n"
            ),
        )
        .unwrap();
    }
    let sources = "regparse regcomp regexec regenc regerror regext regsyntax regtrav \
        regversion st reggnu unicode unicode_unfold_key unicode_fold1_key unicode_fold2_key \
        unicode_fold3_key ascii utf8 utf16_be utf16_le utf32_be utf32_le euc_jp euc_jp_prop \
        sjis sjis_prop iso8859_1 iso8859_2 iso8859_3 iso8859_4 iso8859_5 iso8859_6 iso8859_7 \
        iso8859_8 iso8859_9 iso8859_10 iso8859_11 iso8859_13 iso8859_14 iso8859_15 iso8859_16 \
        euc_tw euc_kr big5 gb18030 koi8_r cp1251 onig_init";
    let mut build = cc::Build::new();
    build
        .include(&source)
        .include(&out)
        .define("ONIG_STATIC", None)
        .warnings(false);
    for name in sources.split_whitespace() {
        build.file(source.join(format!("{name}.c")));
    }
    build.file("src/bridge.c").compile("hilite_onig");
    println!("cargo:rerun-if-changed=vendor/oniguruma");
    println!("cargo:rerun-if-changed=src/bridge.c");
    if os == "macos" {
        println!("cargo:rustc-link-arg=-undefined");
        println!("cargo:rustc-link-arg=dynamic_lookup");
    }
}
