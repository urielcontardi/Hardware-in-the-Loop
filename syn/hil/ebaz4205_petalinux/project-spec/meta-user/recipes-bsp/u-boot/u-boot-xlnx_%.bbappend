FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://platform-top.h file://bsp.cfg"
SRC_URI += "file://user_2026-04-12-19-53-00.cfg"


# Host workaround: this machine cannot create bitbake network namespaces for
# local U-Boot tasks used while assembling the image.
do_unpack[network] = "1"
do_prepare_recipe_sysroot[network] = "1"
do_patch[network] = "1"
do_configure[network] = "1"
do_compile[network] = "1"
do_create_extlinux_config[network] = "1"
do_uboot_generate_rsa_keys[network] = "1"
do_uboot_assemble_fitimage[network] = "1"
do_install[network] = "1"
do_deploy[network] = "1"
do_package[network] = "1"
do_package_qa[network] = "1"
do_package_write_rpm[network] = "1"
do_populate_sysroot[network] = "1"
do_packagedata[network] = "1"
do_create_spdx[network] = "1"
do_collect_spdx_deps[network] = "1"
do_create_runtime_spdx[network] = "1"
do_rm_work[network] = "1"
