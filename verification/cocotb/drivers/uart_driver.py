"""
UART Driver for cocotb testbenches.

Provides UartTx (host → DUT) and UartRx (DUT → host) drivers that operate
at a configurable baud rate. All timing is derived from the simulation clock.

Usage:
    uart_tx = UartTxDriver(baud_rate=115200, clk_freq=100e6)
    uart_rx = UartRxDriver(baud_rate=115200, clk_freq=100e6)

    await uart_tx.send_byte(dut.uart_rx_i, dut.clk_i, 0x57)
    byte = await uart_rx.recv_byte(dut.uart_tx_o, dut.clk_i)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles


class UartTxDriver:
    """Drives the UART RX pin of the DUT (Host → FPGA direction)."""

    def __init__(self, baud_rate: int = 115200, clk_freq: int = 100_000_000):
        self.baud_rate = baud_rate
        self.clk_freq = clk_freq
        self.bit_period_ns = int(1e9 / baud_rate)

    async def send_byte(self, rx_pin, clk, data: int):
        """Send one byte (8N1) to the DUT's RX pin."""
        # Start bit
        rx_pin.value = 0
        await Timer(self.bit_period_ns, unit="ns")
        # Data bits (LSB first)
        for i in range(8):
            rx_pin.value = (data >> i) & 1
            await Timer(self.bit_period_ns, unit="ns")
        # Stop bit
        rx_pin.value = 1
        await Timer(self.bit_period_ns, unit="ns")

    async def send_bytes(self, rx_pin, clk, data: bytes | list[int]):
        """Send multiple bytes sequentially."""
        for b in data:
            await self.send_byte(rx_pin, clk, b)


class UartRxDriver:
    """Captures data from the UART TX pin of the DUT (FPGA → Host direction)."""

    def __init__(self, baud_rate: int = 115200, clk_freq: int = 100_000_000):
        self.baud_rate = baud_rate
        self.clk_freq = clk_freq
        self.bit_period_ns = int(1e9 / baud_rate)

    async def recv_byte(self, tx_pin, clk, timeout_ns: int | None = None) -> int:
        """
        Wait for and receive one byte (8N1) from the DUT's TX pin.
        Raises TimeoutError if no start bit within timeout.
        """
        if timeout_ns is None:
            timeout_ns = self.bit_period_ns * 200

        # Wait for start bit (falling edge: tx goes to 0)
        elapsed = 0
        poll_ns = self.bit_period_ns // 10  # fine-grained polling
        while True:
            try:
                val = int(tx_pin.value)
            except (ValueError, TypeError):
                # Handle uninitialized signals ('U', 'X', etc.)
                val = 1  # treat as idle
            if val == 0:
                break
            await Timer(poll_ns, unit="ns")
            elapsed += poll_ns
            if elapsed >= timeout_ns:
                raise TimeoutError(
                    f"UART RX timeout: no start bit within {timeout_ns} ns"
                )

        # Center on first data bit
        await Timer(self.bit_period_ns + self.bit_period_ns // 2, unit="ns")

        # Sample 8 data bits (LSB first)
        data = 0
        for i in range(8):
            try:
                bit = int(tx_pin.value)
            except (ValueError, TypeError):
                bit = 0
            data |= bit << i
            await Timer(self.bit_period_ns, unit="ns")

        # Wait through remainder of stop bit
        await Timer(self.bit_period_ns // 2, unit="ns")
        return data

    async def recv_bytes(self, tx_pin, clk, count: int, timeout_ns: int | None = None) -> list[int]:
        """Receive multiple bytes sequentially."""
        result = []
        for _ in range(count):
            b = await self.recv_byte(tx_pin, clk, timeout_ns)
            result.append(b)
        return result
