use serialport::SerialPort;
use std::io::{Read, Write};
use std::time::Duration;
use thiserror::Error;

pub const CMD_WRITE: u8 = 0x57;
pub const CMD_READ: u8 = 0x52;
pub const CMD_READ_ALL: u8 = 0x41;

pub const RSP_SINGLE: u8 = 0xAA;
pub const RSP_ALL: u8 = 0x55;

pub const NUM_REGS: usize = 10;

#[derive(Clone, Copy)]
#[repr(u8)]
pub enum RegAddr {
    VdcBus = 0x00,
    TorqueLoad = 0x01,
    VaMotor = 0x02,
    VbMotor = 0x03,
    VcMotor = 0x04,
    IAlpha = 0x05,
    IBeta = 0x06,
    FluxAlpha = 0x07,
    FluxBeta = 0x08,
    SpeedMech = 0x09,
}

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("serial io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("serial port error: {0}")]
    SerialPort(#[from] serialport::Error),

    #[error("invalid response header: expected 0x{expected:02X}, got 0x{got:02X}")]
    InvalidHeader { expected: u8, got: u8 },

    #[error("address mismatch: expected 0x{expected:02X}, got 0x{got:02X}")]
    AddressMismatch { expected: u8, got: u8 },

    #[error("unsupported width: {0}")]
    UnsupportedWidth(u8),
}

pub struct SerialManagerClient {
    port: Box<dyn SerialPort>,
    data_width: u8,
    bytes_per_word: usize,
}

impl SerialManagerClient {
    pub fn open(port_name: &str, baud_rate: u32, timeout: Duration, data_width: u8) -> Result<Self, ProtocolError> {
        if data_width == 0 || data_width > 63 {
            return Err(ProtocolError::UnsupportedWidth(data_width));
        }

        let port = serialport::new(port_name, baud_rate)
            .timeout(timeout)
            .open()?;

        Ok(Self {
            port,
            data_width,
            bytes_per_word: usize::from((data_width + 7) / 8),
        })
    }

    pub fn write_register(&mut self, addr: RegAddr, value: i64) -> Result<(), ProtocolError> {
        let mut frame = Vec::with_capacity(2 + self.bytes_per_word);
        frame.push(CMD_WRITE);
        frame.push(addr as u8);
        frame.extend(to_word_bytes(value, self.bytes_per_word));
        self.port.write_all(&frame)?;
        self.port.flush()?;
        Ok(())
    }

    pub fn read_register(&mut self, addr: RegAddr) -> Result<i64, ProtocolError> {
        let frame = [CMD_READ, addr as u8];
        self.port.write_all(&frame)?;
        self.port.flush()?;

        let mut header = [0u8; 1];
        self.port.read_exact(&mut header)?;
        if header[0] != RSP_SINGLE {
            return Err(ProtocolError::InvalidHeader {
                expected: RSP_SINGLE,
                got: header[0],
            });
        }

        let mut rd_addr = [0u8; 1];
        self.port.read_exact(&mut rd_addr)?;
        if rd_addr[0] != addr as u8 {
            return Err(ProtocolError::AddressMismatch {
                expected: addr as u8,
                got: rd_addr[0],
            });
        }

        let mut data = vec![0u8; self.bytes_per_word];
        self.port.read_exact(&mut data)?;
        Ok(from_word_bytes_signed(&data, self.data_width))
    }

    pub fn read_all(&mut self) -> Result<[i64; NUM_REGS], ProtocolError> {
        self.port.write_all(&[CMD_READ_ALL])?;
        self.port.flush()?;

        let mut header = [0u8; 1];
        self.port.read_exact(&mut header)?;
        if header[0] != RSP_ALL {
            return Err(ProtocolError::InvalidHeader {
                expected: RSP_ALL,
                got: header[0],
            });
        }

        let mut regs = [0_i64; NUM_REGS];
        let mut word = vec![0u8; self.bytes_per_word];

        for reg in &mut regs {
            self.port.read_exact(&mut word)?;
            *reg = from_word_bytes_signed(&word, self.data_width);
        }

        Ok(regs)
    }
}

fn to_word_bytes(value: i64, bytes_per_word: usize) -> Vec<u8> {
    let total_bits = bytes_per_word * 8;
    let mask = if total_bits >= 64 {
        u64::MAX
    } else {
        (1u64 << total_bits) - 1
    };

    let raw = (value as u64) & mask;

    let mut out = vec![0u8; bytes_per_word];
    for (i, byte) in out.iter_mut().enumerate() {
        let shift = 8 * (bytes_per_word - 1 - i);
        *byte = ((raw >> shift) & 0xFF) as u8;
    }
    out
}

fn from_word_bytes_signed(bytes: &[u8], data_width: u8) -> i64 {
    let mut raw = 0u64;
    for byte in bytes {
        raw = (raw << 8) | u64::from(*byte);
    }

    let width = u32::from(data_width);
    if width == 64 {
        return raw as i64;
    }

    let value_mask = if width == 0 { 0 } else { (1u64 << width) - 1 };
    let value = raw & value_mask;

    let sign_bit = 1u64 << (width - 1);
    if (value & sign_bit) != 0 {
        let ext_mask = !value_mask;
        (value | ext_mask) as i64
    } else {
        value as i64
    }
}
