"""
SerialManager Protocol Driver for cocotb.

High-level driver that implements the register read/write protocol
defined in SerialManager.vhd, built on top of the UART driver.

Register Map:
    0x00  VDC_BUS       (R/W)
    0x01  TORQUE_LOAD   (R/W)
    0x02  VA_MOTOR      (R)
    0x03  VB_MOTOR      (R)
    0x04  VC_MOTOR      (R)
    0x05  I_ALPHA       (R)
    0x06  I_BETA        (R)
    0x07  FLUX_ALPHA    (R)   -- Rotor flux alpha
    0x08  FLUX_BETA     (R)   -- Rotor flux beta
    0x09  SPEED_MECH    (R)
"""

import struct
from dataclasses import dataclass
from drivers.uart_driver import UartTxDriver, UartRxDriver


# ── Register Addresses ─────────────────────────────────────────────────
class RegAddr:
    VDC_BUS     = 0x00
    TORQUE_LOAD = 0x01
    VA_MOTOR    = 0x02
    VB_MOTOR    = 0x03
    VC_MOTOR    = 0x04
    I_ALPHA     = 0x05
    I_BETA      = 0x06
    FLUX_ALPHA  = 0x07
    FLUX_BETA   = 0x08
    SPEED_MECH  = 0x09

    NUM_REGS    = 10

    NAMES = {
        0x00: "VDC_BUS",
        0x01: "TORQUE_LOAD",
        0x02: "VA_MOTOR",
        0x03: "VB_MOTOR",
        0x04: "VC_MOTOR",
        0x05: "I_ALPHA",
        0x06: "I_BETA",
        0x07: "FLUX_ALPHA",
        0x08: "FLUX_BETA",
        0x09: "SPEED_MECH",
    }


# ── Command & Response Bytes ──────────────────────────────────────────
CMD_WRITE    = 0x57  # 'W'
CMD_READ     = 0x52  # 'R'
CMD_READ_ALL = 0x41  # 'A'

RSP_SINGLE   = 0xAA
RSP_ALL      = 0x55


@dataclass
class ReadResponse:
    """Response from a single-register read."""
    header: int
    address: int
    value: int

    @property
    def signed_value(self) -> int:
        """Interpret value as signed (42-bit, sign-extended)."""
        if self.value & (1 << 41):
            return self.value - (1 << 42)
        return self.value


@dataclass
class ReadAllResponse:
    """Response from a Read All command."""
    header: int
    registers: dict[int, int]  # addr → value

    def signed_value(self, addr: int, data_width: int = 42) -> int:
        """Interpret register value as signed."""
        val = self.registers.get(addr, 0)
        if val & (1 << (data_width - 1)):
            return val - (1 << data_width)
        return val


class SerialManagerDriver:
    """
    High-level driver for the SerialManager UART protocol.
    
    Args:
        rx_pin:     DUT's uart_rx_i signal (we drive this)
        tx_pin:     DUT's uart_tx_o signal (we read this)
        clk:        DUT's clock signal
        baud_rate:  UART baud rate (must match DUT generic)
        clk_freq:   Clock frequency (must match DUT generic)
        data_width: Register data width in bits (default 42)
    """

    def __init__(
        self,
        rx_pin,
        tx_pin,
        clk,
        baud_rate: int = 115200,
        clk_freq: int = 100_000_000,
        data_width: int = 42,
    ):
        self.rx_pin = rx_pin
        self.tx_pin = tx_pin
        self.clk = clk
        self.data_width = data_width
        self.bytes_per_word = (data_width + 7) // 8  # 6 for 42-bit

        self.uart_tx = UartTxDriver(baud_rate, clk_freq)
        self.uart_rx = UartRxDriver(baud_rate, clk_freq)

    def _value_to_bytes(self, value: int) -> list[int]:
        """Convert integer value to big-endian byte list (BYTES_PER_WORD bytes)."""
        # Handle negative values (two's complement)
        if value < 0:
            value = value + (1 << (self.bytes_per_word * 8))
        result = []
        for i in range(self.bytes_per_word - 1, -1, -1):
            result.append((value >> (i * 8)) & 0xFF)
        return result

    def _bytes_to_value(self, data: list[int]) -> int:
        """Convert big-endian byte list to unsigned integer."""
        value = 0
        for b in data:
            value = (value << 8) | b
        return value

    async def write_register(self, addr: int, value: int):
        """
        Write a value to a configuration register.
        
        Protocol: 'W' (0x57) | ADDR (1B) | DATA (BYTES_PER_WORD bytes, MSB first)
        """
        payload = [CMD_WRITE, addr & 0xFF] + self._value_to_bytes(value)
        await self.uart_tx.send_bytes(self.rx_pin, self.clk, payload)

    async def read_register(self, addr: int) -> ReadResponse:
        """
        Read a single register value.
        
        TX Protocol: 'R' (0x52) | ADDR (1B)
        RX Response: 0xAA | ADDR (1B) | DATA (BYTES_PER_WORD bytes, MSB first)
        """
        # Send read command
        await self.uart_tx.send_bytes(self.rx_pin, self.clk, [CMD_READ, addr & 0xFF])

        # Receive response
        header = await self.uart_rx.recv_byte(self.tx_pin, self.clk)
        rd_addr = await self.uart_rx.recv_byte(self.tx_pin, self.clk)
        data_bytes = await self.uart_rx.recv_bytes(
            self.tx_pin, self.clk, self.bytes_per_word
        )
        value = self._bytes_to_value(data_bytes)

        return ReadResponse(header=header, address=rd_addr, value=value)

    async def read_all(self) -> ReadAllResponse:
        """
        Read all registers at once.
        
        TX Protocol: 'A' (0x41)
        RX Response: 0x55 | REG0_DATA | REG1_DATA | ... | REG9_DATA
        """
        # Increase timeout for Read All: generous per-byte timeout
        total_bytes = 1 + RegAddr.NUM_REGS * self.bytes_per_word
        timeout_ns = self.uart_rx.bit_period_ns * 12 * total_bytes * 4

        await self.uart_tx.send_byte(self.rx_pin, self.clk, CMD_READ_ALL)

        header = await self.uart_rx.recv_byte(self.tx_pin, self.clk, timeout_ns)
        registers = {}
        for reg_addr in range(RegAddr.NUM_REGS):
            data_bytes = await self.uart_rx.recv_bytes(
                self.tx_pin, self.clk, self.bytes_per_word, timeout_ns
            )
            registers[reg_addr] = self._bytes_to_value(data_bytes)

        return ReadAllResponse(header=header, registers=registers)

    # ── Convenience Methods ────────────────────────────────────────────

    async def set_vdc_bus(self, value: int):
        """Write DC bus voltage register."""
        await self.write_register(RegAddr.VDC_BUS, value)

    async def set_torque_load(self, value: int):
        """Write motor load torque register."""
        await self.write_register(RegAddr.TORQUE_LOAD, value)

    async def get_vdc_bus(self) -> ReadResponse:
        """Read DC bus voltage register."""
        return await self.read_register(RegAddr.VDC_BUS)

    async def get_torque_load(self) -> ReadResponse:
        """Read motor load torque register."""
        return await self.read_register(RegAddr.TORQUE_LOAD)

    async def get_speed(self) -> ReadResponse:
        """Read mechanical speed register."""
        return await self.read_register(RegAddr.SPEED_MECH)

    async def get_currents(self) -> tuple[ReadResponse, ReadResponse]:
        """Read both stator current registers (alpha, beta)."""
        ia = await self.read_register(RegAddr.I_ALPHA)
        ib = await self.read_register(RegAddr.I_BETA)
        return ia, ib

    async def get_fluxes(self) -> tuple[ReadResponse, ReadResponse]:
        """Read both stator flux registers (alpha, beta)."""
        fa = await self.read_register(RegAddr.FLUX_ALPHA)
        fb = await self.read_register(RegAddr.FLUX_BETA)
        return fa, fb
