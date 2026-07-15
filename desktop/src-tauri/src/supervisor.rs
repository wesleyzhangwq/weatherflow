use crate::credentials::{random_token, CredentialBrokerConfig};
use serde::Serialize;
#[cfg(debug_assertions)]
use std::io::Write;
#[cfg(not(debug_assertions))]
use std::net::TcpListener;
#[cfg(debug_assertions)]
use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;
use tauri::AppHandle;
#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(debug_assertions)]
const DEVELOPMENT_PORT: u16 = 8765;
#[cfg(any(not(debug_assertions), test))]
const INITIAL_HEALTH_GRACE: Duration = Duration::from_secs(60);
#[cfg(any(not(debug_assertions), test))]
const HEALTH_FAILURE_THRESHOLD: u8 = 3;

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

#[derive(Serialize)]
struct DesktopBootstrap<'a> {
    version: u8,
    bridge_token: &'a str,
    credential_socket: &'a std::path::Path,
    credential_token: &'a str,
}

pub struct DaemonSupervisor {
    child: Option<DaemonChild>,
    pub bridge: BridgeConfig,
    credential_bootstrap: CredentialBrokerConfig,
    failures: u32,
}

impl DaemonSupervisor {
    pub fn start(
        app: &AppHandle,
        credential_bootstrap: CredentialBrokerConfig,
    ) -> Result<Self, String> {
        let (child, bridge) = spawn_sidecar(app, &credential_bootstrap)?;
        Ok(Self {
            child: Some(child),
            bridge,
            credential_bootstrap,
            failures: 0,
        })
    }

    fn replace(&mut self, app: &AppHandle) -> Result<(), String> {
        if let Some(child) = self.child.take() {
            child.kill();
        }
        let (child, bridge) = spawn_sidecar(app, &self.credential_bootstrap)?;
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

fn spawn_sidecar(
    app: &AppHandle,
    credential_bootstrap: &CredentialBrokerConfig,
) -> Result<(DaemonChild, BridgeConfig), String> {
    #[cfg(debug_assertions)]
    let port = DEVELOPMENT_PORT;
    #[cfg(not(debug_assertions))]
    let port = {
        let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
        let port = listener
            .local_addr()
            .map_err(|error| error.to_string())?
            .port();
        drop(listener);
        port
    };
    let token = random_token()?;
    let child = spawn_core(app, port, &token, credential_bootstrap)?;
    Ok((
        child,
        BridgeConfig {
            base_url: format!("http://127.0.0.1:{port}"),
            token,
        },
    ))
}

fn bootstrap_message(
    bridge_token: &str,
    credential_bootstrap: &CredentialBrokerConfig,
) -> Result<Vec<u8>, String> {
    let mut message = serde_json::to_vec(&DesktopBootstrap {
        version: 1,
        bridge_token,
        credential_socket: &credential_bootstrap.socket_path,
        credential_token: credential_bootstrap.bootstrap_token(),
    })
    .map_err(|_| "desktop_bootstrap_unavailable".to_owned())?;
    message.push(b'\n');
    Ok(message)
}

#[cfg(debug_assertions)]
fn spawn_core(
    _app: &AppHandle,
    port: u16,
    token: &str,
    credential_bootstrap: &CredentialBrokerConfig,
) -> Result<DaemonChild, String> {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map_err(|error| format!("cannot resolve WeatherFlow source root: {error}"))?;
    wait_for_development_port(port)?;
    let mut child = std::process::Command::new("uv")
        .current_dir(root)
        .args(development_daemon_args(port))
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .spawn()
        .map_err(|error| format!("cannot start live Python core through uv: {error}"))?;
    let result = child
        .stdin
        .as_mut()
        .ok_or_else(|| "desktop_bootstrap_unavailable".to_owned())?
        .write_all(&bootstrap_message(token, credential_bootstrap)?);
    if result.is_err() {
        let _ = child.kill();
        return Err("desktop_bootstrap_unavailable".to_owned());
    }
    Ok(DaemonChild::Development(child))
}

#[cfg(debug_assertions)]
fn wait_for_development_port(port: u16) -> Result<(), String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    for _ in 0..100 {
        if TcpStream::connect_timeout(&address, Duration::from_millis(20)).is_err() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Err("development_daemon_port_unavailable".to_owned())
}

#[cfg(not(debug_assertions))]
fn spawn_core(
    app: &AppHandle,
    port: u16,
    token: &str,
    credential_bootstrap: &CredentialBrokerConfig,
) -> Result<DaemonChild, String> {
    let command = app
        .shell()
        .sidecar("weatherflow-core")
        .map_err(|error| error.to_string())?
        .args([
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--desktop-bootstrap-stdin",
        ]);
    let (_events, mut child) = command.spawn().map_err(|error| error.to_string())?;
    if child
        .write(&bootstrap_message(token, credential_bootstrap)?)
        .is_err()
    {
        let _ = child.kill();
        return Err("desktop_bootstrap_unavailable".to_owned());
    }
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
        "--desktop-bootstrap-stdin",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

#[cfg(any(not(debug_assertions), test))]
pub fn restart_delay(failures: u32) -> Duration {
    Duration::from_millis((500_u64.saturating_mul(2_u64.saturating_pow(failures))).min(5_000))
}

#[cfg(any(not(debug_assertions), test))]
fn should_restart_after_health_failure(consecutive_failures: u8) -> bool {
    consecutive_failures >= HEALTH_FAILURE_THRESHOLD
}

#[cfg(not(debug_assertions))]
pub fn monitor(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let client = reqwest::Client::new();
        let mut consecutive_failures = 0_u8;
        tokio_sleep(INITIAL_HEALTH_GRACE).await;
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
                consecutive_failures = 0;
                if let Ok(mut state) = app.state::<Mutex<DaemonSupervisor>>().lock() {
                    state.failures = 0;
                }
                continue;
            }
            consecutive_failures = consecutive_failures.saturating_add(1);
            if !should_restart_after_health_failure(consecutive_failures) {
                continue;
            }
            consecutive_failures = 0;
            let delay = {
                let state = app.state::<Mutex<DaemonSupervisor>>();
                let failures = state.lock().expect("daemon state poisoned").failures;
                restart_delay(failures)
            };
            tokio_sleep(delay).await;
            let replaced = app
                .state::<Mutex<DaemonSupervisor>>()
                .lock()
                .ok()
                .is_some_and(|mut state| state.replace(&app).is_ok());
            if replaced {
                tokio_sleep(INITIAL_HEALTH_GRACE).await;
            }
        }
    });
}

#[cfg(not(debug_assertions))]
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
    use super::{
        development_daemon_args, restart_delay, should_restart_after_health_failure,
        DEVELOPMENT_PORT, INITIAL_HEALTH_GRACE,
    };
    use std::time::Duration;

    #[test]
    fn restart_backoff_is_bounded() {
        assert_eq!(INITIAL_HEALTH_GRACE, Duration::from_secs(60));
        assert_eq!(restart_delay(0), Duration::from_millis(500));
        assert_eq!(restart_delay(1), Duration::from_millis(1_000));
        assert_eq!(restart_delay(20), Duration::from_millis(5_000));
    }

    #[test]
    fn every_bundled_daemon_spawn_gets_the_full_startup_grace() {
        let source = include_str!("supervisor.rs");
        let startup_wait = ["tokio_sleep(", "INITIAL_HEALTH_GRACE).await;"].concat();
        assert_eq!(source.matches(&startup_wait).count(), 2);
    }

    #[test]
    fn transient_health_failures_do_not_restart_the_daemon() {
        assert!(!should_restart_after_health_failure(1));
        assert!(!should_restart_after_health_failure(2));
        assert!(should_restart_after_health_failure(3));
    }

    #[test]
    fn debug_app_starts_the_python_core_with_private_stdin_bootstrap() {
        assert_eq!(DEVELOPMENT_PORT, 8765);
        assert_eq!(
            development_daemon_args(DEVELOPMENT_PORT),
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
                "--desktop-bootstrap-stdin",
            ]
        );
    }
}
