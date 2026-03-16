mod protocol;
mod state;

use protocol::{RegAddr, SerialManagerClient};
use serde::{Deserialize, Serialize};
use state::{AppState, RunningStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Emitter, State};

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StreamConfig {
    port_name: String,
    baud_rate: u32,
    sample_hz: u32,
    flush_ms: u64,
    chunk_samples: usize,
    data_width: u8,
}

#[derive(Clone, Debug, Serialize)]
struct TelemetrySample {
    t_ms: u64,
    regs: [i64; protocol::NUM_REGS],
}

#[tauri::command]
fn list_serial_ports() -> Result<Vec<String>, String> {
    serialport::available_ports()
        .map_err(|e| e.to_string())
        .map(|ports| ports.into_iter().map(|p| p.port_name).collect())
}

#[tauri::command]
fn write_vdc_bus(port_name: String, baud_rate: u32, value: i64, data_width: u8) -> Result<(), String> {
    with_client(&port_name, baud_rate, data_width, |client| {
        client.write_register(RegAddr::VdcBus, value)
    })
}

#[tauri::command]
fn write_torque_load(port_name: String, baud_rate: u32, value: i64, data_width: u8) -> Result<(), String> {
    with_client(&port_name, baud_rate, data_width, |client| {
        client.write_register(RegAddr::TorqueLoad, value)
    })
}

#[tauri::command]
fn read_all_once(port_name: String, baud_rate: u32, data_width: u8) -> Result<[i64; protocol::NUM_REGS], String> {
    with_client(&port_name, baud_rate, data_width, |client| client.read_all())
}

#[tauri::command]
fn stream_status(state: State<AppState>) -> Result<bool, String> {
    state.is_running()
}

#[tauri::command]
fn start_stream(app: tauri::AppHandle, state: State<AppState>, config: StreamConfig) -> Result<(), String> {
    if config.port_name.is_empty() {
        return Err("port is required".to_string());
    }
    if config.baud_rate < 1200 {
        return Err("baud rate seems invalid".to_string());
    }
    if config.sample_hz == 0 {
        return Err("sampleHz must be greater than zero".to_string());
    }
    if state.is_running()? {
        return Err("stream is already running".to_string());
    }

    let stop = Arc::new(AtomicBool::new(false));
    let stop_thread = Arc::clone(&stop);

    let stream_cfg = config.clone();
    let app_handle = app.clone();

    let handle = thread::spawn(move || {
        let timeout = Duration::from_millis(90);
        let mut client = match SerialManagerClient::open(
            &stream_cfg.port_name,
            stream_cfg.baud_rate,
            timeout,
            stream_cfg.data_width,
        ) {
            Ok(client) => client,
            Err(err) => {
                let _ = app_handle.emit("stream-error", format!("stream open failed: {err}"));
                return;
            }
        };

        let mut chunk = Vec::<TelemetrySample>::with_capacity(stream_cfg.chunk_samples.max(2));
        let stream_start = Instant::now();
        let mut last_flush = Instant::now();

        let sample_period = Duration::from_secs_f64(1.0 / f64::from(stream_cfg.sample_hz));
        let flush_period = Duration::from_millis(stream_cfg.flush_ms.max(10));
        let mut next_tick = Instant::now();

        while !stop_thread.load(Ordering::Relaxed) {
            match client.read_all() {
                Ok(regs) => {
                    chunk.push(TelemetrySample {
                        t_ms: stream_start.elapsed().as_millis() as u64,
                        regs,
                    });
                }
                Err(err) => {
                    let _ = app_handle.emit("stream-error", format!("stream read failed: {err}"));
                    thread::sleep(Duration::from_millis(20));
                }
            }

            if chunk.len() >= stream_cfg.chunk_samples.max(2) || last_flush.elapsed() >= flush_period {
                if !chunk.is_empty() {
                    let outbound = std::mem::take(&mut chunk);
                    let _ = app_handle.emit("telemetry-chunk", outbound);
                }
                last_flush = Instant::now();
            }

            next_tick += sample_period;
            let now = Instant::now();
            if next_tick > now {
                thread::sleep(next_tick - now);
            } else {
                next_tick = now;
            }
        }

        if !chunk.is_empty() {
            let _ = app_handle.emit("telemetry-chunk", chunk);
        }
    });

    state.start_stream(RunningStream { stop, handle })
}

#[tauri::command]
fn stop_stream(state: State<AppState>) -> Result<(), String> {
    state.stop_stream()
}

fn with_client<T, F>(port_name: &str, baud_rate: u32, data_width: u8, f: F) -> Result<T, String>
where
    F: FnOnce(&mut SerialManagerClient) -> Result<T, protocol::ProtocolError>,
{
    let mut client = SerialManagerClient::open(port_name, baud_rate, Duration::from_millis(80), data_width)
        .map_err(|e| e.to_string())?;
    f(&mut client).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .manage(AppState::new())
        .invoke_handler(tauri::generate_handler![
            list_serial_ports,
            write_vdc_bus,
            write_torque_load,
            read_all_once,
            stream_status,
            start_stream,
            stop_stream
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
