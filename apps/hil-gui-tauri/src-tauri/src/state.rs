use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

pub struct RunningStream {
    pub stop: Arc<AtomicBool>,
    pub handle: JoinHandle<()>,
}

#[derive(Default)]
pub struct AppState {
    stream: Mutex<Option<RunningStream>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            stream: Mutex::new(None),
        }
    }

    pub fn start_stream(&self, stream: RunningStream) -> Result<(), String> {
        let mut guard = self
            .stream
            .lock()
            .map_err(|_| "stream mutex poisoned".to_string())?;

        if guard.is_some() {
            return Err("stream is already running".to_string());
        }

        *guard = Some(stream);
        Ok(())
    }

    pub fn stop_stream(&self) -> Result<(), String> {
        let stream = {
            let mut guard = self
                .stream
                .lock()
                .map_err(|_| "stream mutex poisoned".to_string())?;
            guard.take()
        };

        if let Some(stream) = stream {
            stream.stop.store(true, Ordering::Relaxed);
            stream
                .handle
                .join()
                .map_err(|_| "failed to join stream thread".to_string())?;
            Ok(())
        } else {
            Err("stream is not running".to_string())
        }
    }

    pub fn is_running(&self) -> Result<bool, String> {
        let guard = self
            .stream
            .lock()
            .map_err(|_| "stream mutex poisoned".to_string())?;
        Ok(guard.is_some())
    }
}
