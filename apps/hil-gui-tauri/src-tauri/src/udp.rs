use serde::{Deserialize, Serialize};
use std::net::UdpSocket;
use std::time::Duration;

const UDP_PORT: u16 = 5005;
const TIMEOUT_MS: u64 = 2000;

// ── Response from {"cmd":"get"} ───────────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HilStatus {
    pub speed_rad_s:   f32,
    #[serde(rename = "ialpha_A")]
    pub ialpha_a:      f32,
    #[serde(rename = "ibeta_A")]
    pub ibeta_a:       f32,
    #[serde(rename = "flux_alpha_Wb")]
    pub flux_alpha_wb: f32,
    #[serde(rename = "flux_beta_Wb")]
    pub flux_beta_wb:  f32,
    pub freq_hz:       f32,
    pub vdc_v:         f32,
    pub enable:        i32,
}

// ── Low-level send/recv ───────────────────────────────────────────────────────
fn send_recv(ip: &str, payload: &str) -> Result<String, String> {
    let addr = format!("{ip}:{UDP_PORT}");

    let sock = UdpSocket::bind("0.0.0.0:0").map_err(|e| e.to_string())?;
    sock.set_read_timeout(Some(Duration::from_millis(TIMEOUT_MS)))
        .map_err(|e| e.to_string())?;
    sock.send_to(payload.as_bytes(), &addr)
        .map_err(|e| format!("send error: {e}"))?;

    let mut buf = [0u8; 1024];
    let (n, _) = sock
        .recv_from(&mut buf)
        .map_err(|e| format!("recv timeout or error: {e}"))?;

    String::from_utf8(buf[..n].to_vec()).map_err(|e| e.to_string())
}

// ── Public API ────────────────────────────────────────────────────────────────

pub fn hil_set(
    ip: &str,
    freq_hz: f32,
    vdc_v: f32,
    torque_nm: f32,
    enable: bool,
) -> Result<(), String> {
    let cmd = format!(
        r#"{{"cmd":"set","freq_hz":{freq_hz:.2},"vdc_v":{vdc_v:.2},"torque_nm":{torque_nm:.4},"enable":{enable}}}"#,
        enable = if enable { 1 } else { 0 }
    );
    let resp = send_recv(ip, &cmd)?;
    if resp.contains("\"ok\"") || resp.contains("ok") {
        Ok(())
    } else {
        Err(format!("unexpected response: {resp}"))
    }
}

pub fn hil_get(ip: &str) -> Result<HilStatus, String> {
    let resp = send_recv(ip, r#"{"cmd":"get"}"#)?;
    serde_json::from_str::<HilStatus>(&resp)
        .map_err(|e| format!("parse error: {e} — raw: {resp}"))
}

pub fn hil_stop(ip: &str) -> Result<(), String> {
    send_recv(ip, r#"{"cmd":"stop"}"#)?;
    Ok(())
}
