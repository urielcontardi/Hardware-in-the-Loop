FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " file://bsp.cfg"
KERNEL_FEATURES:append = " bsp.cfg"

# Host workaround: this machine cannot create bitbake network namespaces for
# the local FIT image assembly task.
do_assemble_fitimage[network] = "1"
do_assemble_fitimage_initramfs[network] = "1"
do_bundle_initramfs[network] = "1"
do_install[network] = "1"
do_deploy[network] = "1"
do_package[network] = "1"
do_package_qa[network] = "1"
do_package_write_rpm[network] = "1"
do_populate_sysroot[network] = "1"
do_packagedata[network] = "1"
do_create_spdx[network] = "1"
do_create_runtime_spdx[network] = "1"
do_rm_work[network] = "1"
