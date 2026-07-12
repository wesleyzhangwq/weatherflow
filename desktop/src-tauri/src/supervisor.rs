use serde::Serialize;
use std::{net::TcpListener, sync::Mutex, time::Duration};
use tauri::{AppHandle, Manager};
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

enum DaemonChild {
    #[cfg(debug_assertions)]
    Development(std::process::Child),
    #[cfg(not(debug_assertions))]
    Bundled(CommandChild),
}

impl DaemonChild {
    fn kill(self) {
        match self {
            #[cfg(debug_assertions)]
            Self::Development(mut child) => {
                let _ = child.kill();
            }
            #[cfg(not(debug_assertions))]
            Self::Bundled(child) => {
                let _ = child.kill();
            }
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeConfig {
    pub base_url: String,
    pub token: String,
}

pub struct DaemonSupervisor {
    child: Option<DaemonChild>,
    pub bridge: BridgeConfig,
    failures: u32,
}

impl DaemonSupervisor {
    pub fn start(app: &AppHandle) -> Result<Self, String> {
        let (child, bridge) = spawn_sidecar(app)?;
        Ok(Self {
            child: Some(child),
            bridge,
            failures: 0,
        })
    }

    fn replace(&mut self, app: &AppHandle) -> Result<(), String> {
        if let Some(child) = self.child.take() {
            child.kill();
        }
        let (child, bridge) = spawn_sidecar(app)?;
        self.child = Some(child);
        self.bridge = bridge;
        self.failures = self.failures.saturating_add(1);
        Ok(())
    }
}

impl Drop for DaemonSupervisor {
    fn drop(&mut self) {
        if let Some(child) = self.child.take() {
            child.kill();
        }
    }
}

fn spawn_sidecar(app: &AppHandle) -> Result<(DaemonChild, BridgeConfig), String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    drop(listener);
    let token = Uuid::new_v4().to_string();
    let child = spawn_core(app, port, &token)?;
    Ok((
        child,
        BridgeConfig {
            base_url: format!("http://127.0.0.1:{port}"),
            token,
        },
    ))
}

#[cfg(debug_assertions)]
fn spawn_core(_app: &AppHandle, port: u16, token: &str) -> Result<DaemonChild, String> {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map_err(|error| format!("cannot resolve WeatherFlow source root: {error}"))?;
    let child = std::process::Command::new("uv")
        .current_dir(root)
        .args(development_daemon_args(port))
        .env("WF_BRIDGE_TOKEN", token)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .spawn()
        .map_err(|error| format!("cannot start live Python core through uv: {error}"))?;
    Ok(DaemonChild::Development(child))
}

#[cfg(not(debug_assertions))]
fn spawn_core(app: &AppHandle, port: u16, token: &str) -> Result<DaemonChild, String> {
    let command = app
        .shell()
        .sidecar("weatherflow-core")
        .map_err(|error| error.to_string())?
        .args(["serve", "--host", "127.0.0.1", "--port", &port.to_string()])
        .env("WF_BRIDGE_TOKEN", token);
    let (_events, child) = command.spawn().map_err(|error| error.to_string())?;
    Ok(DaemonChild::Bundled(child))
}

#[cfg(debug_assertions)]
fn development_daemon_args(port: u16) -> Vec<String> {
    [
        "run",
        "--package",
        "weatherflow-core",
        "weatherflow",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        &port.to_string(),
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

pub fn restart_delay(failures: u32) -> Duration {
    Duration::from_millis((500_u64.saturating_mul(2_u64.saturating_pow(failures))).min(5_000))
}

pub fn monitor(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let client = reqwest::Client::new();
        loop {
            tokio_sleep(Duration::from_secs(2)).await;
            let bridge = {
                let state = app.state::<Mutex<DaemonSupervisor>>();
                let bridge = state.lock().expect("daemon state poisoned").bridge.clone();
                bridge
            };
            let healthy = client
                .get(format!("{}/health", bridge.base_url))
                .bearer_auth(&bridge.token)
                .timeout(Duration::from_secs(1))
                .send()
                .await
                .is_ok_and(|response| response.status().is_success());
            if healthy {
                if let Ok(mut state) = app.state::<Mutex<DaemonSupervisor>>().lock() {
                    state.failures = 0;
                }
                continue;
            }
            let delay = {
                let state = app.state::<Mutex<DaemonSupervisor>>();
                let failures = state.lock().expect("daemon state poisoned").failures;
                restart_delay(failures)
            };
            tokio_sleep(delay).await;
            if let Ok(mut state) = app.state::<Mutex<DaemonSupervisor>>().lock() {
                let _ = state.replace(&app);
            }
        }
    });
}

async fn tokio_sleep(duration: Duration) {
    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(duration))
        .await
        .ok();
}

#[tauri::command]
pub fn daemon_bridge(state: tauri::State<'_, Mutex<DaemonSupervisor>>) -> BridgeConfig {
    state.lock().expect("daemon state poisoned").bridge.clone()
}

#[tauri::command]
pub fn restart_daemon(
    app: AppHandle,
    state: tauri::State<'_, Mutex<DaemonSupervisor>>,
) -> Result<BridgeConfig, String> {
    let mut supervisor = state
        .lock()
        .map_err(|_| "daemon state poisoned".to_string())?;
    supervisor.replace(&app)?;
    Ok(supervisor.bridge.clone())
}

#[cfg(test)]
mod tests {
    use super::{development_daemon_args, restart_delay};
    use std::time::Duration;

    #[test]
    fn restart_backoff_is_bounded() {
        assert_eq!(restart_delay(0), Duration::from_millis(500));
        assert_eq!(restart_delay(1), Duration::from_millis(1_000));
        assert_eq!(restart_delay(20), Duration::from_millis(5_000));
    }

    #[test]
    fn debug_app_starts_the_live_python_core() {
        assert_eq!(
            development_daemon_args(8765),
            [
                "run",
                "--package",
                "weatherflow-core",
                "weatherflow",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
            ]
        );
    }
}
