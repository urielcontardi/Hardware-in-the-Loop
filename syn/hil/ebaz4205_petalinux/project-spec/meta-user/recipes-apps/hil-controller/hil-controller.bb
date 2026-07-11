SUMMARY = "HIL controller and supervisor"
LICENSE = "CLOSED"

SRC_URI = "file://hil_controller \
           file://hil_supervisor \
           file://test_fpga \
           file://hil-supervisor"

S = "${WORKDIR}"

inherit update-rc.d

INITSCRIPT_NAME = "hil-supervisor"
INITSCRIPT_PARAMS = "defaults 99"

INSANE_SKIP:${PN} += "already-stripped ldflags"

FILES:${PN} += "/home/petalinux/hil_controller \
               /home/petalinux/hil_supervisor \
               /home/petalinux/test_fpga"

do_install() {
    install -d ${D}/home/petalinux
    install -m 0755 ${WORKDIR}/hil_controller ${D}/home/petalinux/hil_controller
    install -m 0755 ${WORKDIR}/hil_supervisor ${D}/home/petalinux/hil_supervisor
    install -m 0755 ${WORKDIR}/test_fpga ${D}/home/petalinux/test_fpga

    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${WORKDIR}/hil-supervisor ${D}${sysconfdir}/init.d/hil-supervisor
}
