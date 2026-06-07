FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://system-user.dtsi"

require ${@'device-tree-sdt.inc' if d.getVar('SYSTEM_DTFILE') != '' else ''}

# Host workaround: this machine cannot create bitbake network namespaces for
# local device-tree tasks. Marking these tasks as network-capable skips that
# namespace isolation only for this recipe; the recipe still uses local files.
do_unpack[network] = "1"
do_prepare_recipe_sysroot[network] = "1"
do_configure[network] = "1"
do_compile[network] = "1"
do_install[network] = "1"
do_deploy[network] = "1"
do_create_yaml[network] = "1"
do_collect_spdx_deps[network] = "1"
do_patch[network] = "1"
do_patch_config[network] = "1"
do_create_runtime_spdx[network] = "1"
do_rm_work[network] = "1"
