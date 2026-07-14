mod activity;
mod credentials;
mod supervisor;

use std::{process::Command, sync::Mutex};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

const STARTUP_SURFACE: &str = "companion";
const SHORTCUT_SURFACE: &str = "capsule";
const STARTUP_SIZE: (f64, f64) = (56.0, 56.0);
const CAPSULE_SIZE: (f64, f64) = (460.0, 58.0);
const COCKPIT_SIZE: (f64, f64) = (1080.0, 760.0);

#[derive(Debug, PartialEq, Eq)]
struct SurfacePolicy {
    always_on_top: bool,
    resizable: bool,
    skip_taskbar: bool,
}

impl SurfacePolicy {
    fn for_surface(surface: &str) -> Self {
        let ambient = surface != "cockpit";
        Self {
            always_on_top: ambient,
            resizable: !ambient,
            skip_taskbar: ambient,
        }
    }
}

fn surface_url(surface: &str) -> WebviewUrl {
    #[cfg(debug_assertions)]
    {
        return WebviewUrl::External(
            format!("http://localhost:1421/?surface={surface}")
                .parse()
                .expect("development surface URL must be valid"),
        );
    }
    #[cfg(not(debug_assertions))]
    {
        WebviewUrl::App(format!("index.html?surface={surface}").into())
    }
}

fn show_or_create(
    app: &tauri::AppHandle,
    label: &str,
    surface: &str,
    width: f64,
    height: f64,
    transparent: bool,
) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window(label) {
        window.show()?;
        window.set_focus()?;
        return Ok(());
    }
    let bridge = app
        .state::<Mutex<supervisor::DaemonSupervisor>>()
        .lock()
        .expect("daemon state poisoned")
        .bridge
        .clone();
    let policy = SurfacePolicy::for_surface(surface);
    let initialization_script = format!(
        "window.__WEATHERFLOW_BRIDGE__ = {};",
        serde_json::to_string(&bridge).expect("bridge config must serialize")
    );
    let window = WebviewWindowBuilder::new(app, label, surface_url(surface))
        .title(format!("WeatherFlow {surface}"))
        .initialization_script(initialization_script)
        .inner_size(width, height)
        .decorations(!transparent)
        .transparent(transparent)
        .always_on_top(policy.always_on_top)
        .resizable(policy.resizable)
        .skip_taskbar(policy.skip_taskbar)
        .build()?;
    if surface == "cockpit" {
        let app_handle = app.clone();
        window.on_window_event(move |event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                restore_companion(&app_handle);
            }
        });
    } else if surface == "capsule" {
        let capsule_handle = app.clone();
        window.on_window_event(move |event| {
            if matches!(event, tauri::WindowEvent::Focused(false)) {
                if let Some(capsule) = capsule_handle.get_webview_window("capsule") {
                    let _ = capsule.hide();
                }
            }
        });
    }
    window.set_focus()?;
    Ok(())
}

fn hide_companion(app: &tauri::AppHandle) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("companion") {
        window.hide()?;
    }
    Ok(())
}

fn restore_companion(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("companion") {
        let _ = window.show();
    }
}

#[tauri::command]
fn open_capsule(app: tauri::AppHandle) -> tauri::Result<()> {
    show_or_create(
        &app,
        "capsule",
        "capsule",
        CAPSULE_SIZE.0,
        CAPSULE_SIZE.1,
        true,
    )
}

#[tauri::command]
fn close_capsule(app: tauri::AppHandle) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("capsule") {
        window.hide()?;
    }
    Ok(())
}

#[tauri::command]
fn open_cockpit(app: tauri::AppHandle) -> tauri::Result<()> {
    show_or_create(
        &app,
        "cockpit",
        "cockpit",
        COCKPIT_SIZE.0,
        COCKPIT_SIZE.1,
        false,
    )?;
    hide_companion(&app)?;
    Ok(())
}

#[tauri::command]
fn choose_workspace_directory() -> Result<Option<String>, String> {
    let output = Command::new("osascript")
        .args([
            "-e",
            "try",
            "-e",
            "POSIX path of (choose folder with prompt \"Choose a project for WeatherFlow\")",
            "-e",
            "on error number -128",
            "-e",
            "return \"\"",
            "-e",
            "end try",
        ])
        .output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    let path = String::from_utf8_lossy(&output.stdout)
        .trim()
        .trim_end_matches('/')
        .to_owned();
    Ok((!path.is_empty()).then_some(path))
}

fn connector_url_is_allowed(value: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(value) else {
        return false;
    };
    if url.scheme() != "https" {
        return false;
    }
    let Some(host) = url.host_str() else {
        return false;
    };
    host == "composio.dev" || host.ends_with(".composio.dev")
}

#[tauri::command]
fn open_connector_url(url: String) -> Result<(), String> {
    if !connector_url_is_allowed(&url) {
        return Err("connector URL is outside the approved Composio HTTPS boundary".to_owned());
    }
    Command::new("open")
        .arg(&url)
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn credential_set(
    provider: credentials::CredentialProvider,
    secret: String,
    state: tauri::State<'_, Mutex<credentials::CredentialBrokerServer>>,
) -> Result<credentials::CredentialStatus, String> {
    state
        .lock()
        .map_err(|_| "credential_unavailable".to_owned())?
        .set(provider, &secret)
}

#[tauri::command]
fn credential_delete(
    provider: credentials::CredentialProvider,
    state: tauri::State<'_, Mutex<credentials::CredentialBrokerServer>>,
) -> Result<credentials::CredentialStatus, String> {
    state
        .lock()
        .map_err(|_| "credential_unavailable".to_owned())?
        .delete(provider)
}

#[tauri::command]
fn credential_status(
    provider: credentials::CredentialProvider,
    state: tauri::State<'_, Mutex<credentials::CredentialBrokerServer>>,
) -> Result<credentials::CredentialStatus, String> {
    state
        .lock()
        .map_err(|_| "credential_unavailable".to_owned())?
        .status(provider)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        let _ = show_or_create(
                            app,
                            SHORTCUT_SURFACE,
                            SHORTCUT_SURFACE,
                            CAPSULE_SIZE.0,
                            CAPSULE_SIZE.1,
                            true,
                        );
                    }
                })
                .build(),
        )
        .setup(|app| {
            let credential_server = credentials::CredentialBrokerServer::start_native()
                .map_err(std::io::Error::other)?;
            let supervisor =
                supervisor::DaemonSupervisor::start(app.handle(), credential_server.config())
                    .map_err(std::io::Error::other)?;
            app.manage(Mutex::new(credential_server));
            app.manage(Mutex::new(supervisor));
            show_or_create(
                app.handle(),
                STARTUP_SURFACE,
                STARTUP_SURFACE,
                STARTUP_SIZE.0,
                STARTUP_SIZE.1,
                true,
            )?;
            #[cfg(not(debug_assertions))]
            supervisor::monitor(app.handle().clone());
            // A previously installed WeatherFlow build may still own the shortcut.
            // The desktop must remain usable through the Companion in that case.
            let _ = app
                .global_shortcut()
                .register("CommandOrControl+Shift+Space");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_capsule,
            close_capsule,
            open_cockpit,
            choose_workspace_directory,
            open_connector_url,
            credential_set,
            credential_delete,
            credential_status,
            supervisor::daemon_bridge,
            supervisor::restart_daemon,
            activity::sample_activity_metadata
        ])
        .run(tauri::generate_context!())
        .expect("WeatherFlow desktop shell failed");
}

#[cfg(test)]
mod tests {
    use super::{
        connector_url_is_allowed, surface_url, SurfacePolicy, CAPSULE_SIZE, SHORTCUT_SURFACE,
        STARTUP_SIZE, STARTUP_SURFACE,
    };
    use tauri::WebviewUrl;

    #[test]
    fn debug_surfaces_load_the_live_vite_frontend() {
        match surface_url("cockpit") {
            WebviewUrl::External(url) => {
                assert_eq!(url.as_str(), "http://localhost:1421/?surface=cockpit")
            }
            other => panic!("debug surface must be external, got {other:?}"),
        }
    }

    #[test]
    fn connector_browser_handoff_only_allows_composio_https_hosts() {
        assert!(connector_url_is_allowed(
            "https://connect.composio.dev/link/opaque"
        ));
        assert!(connector_url_is_allowed("https://composio.dev/connect"));
        assert!(!connector_url_is_allowed(
            "http://connect.composio.dev/link/opaque"
        ));
        assert!(!connector_url_is_allowed(
            "https://composio.dev.evil.example/link"
        ));
        assert!(!connector_url_is_allowed("file:///tmp/secret"));
    }

    #[test]
    fn debug_python_reloader_is_not_competed_by_the_desktop_monitor() {
        let source = include_str!("lib.rs");
        assert!(source.contains(
            "#[cfg(not(debug_assertions))]\n            supervisor::monitor(app.handle().clone());"
        ));
    }

    #[test]
    fn startup_and_shortcut_never_auto_open_cockpit() {
        assert_eq!(STARTUP_SURFACE, "companion");
        assert_eq!(SHORTCUT_SURFACE, "capsule");
        assert_ne!(STARTUP_SURFACE, "cockpit");
        assert_ne!(SHORTCUT_SURFACE, "cockpit");
    }

    #[test]
    fn newly_created_surfaces_are_focused_to_start_the_webview() {
        let source = include_str!("lib.rs");
        assert!(source.contains("window.set_focus()?;"));
    }

    #[test]
    fn companion_and_capsule_use_compact_sizes() {
        assert_eq!(STARTUP_SIZE, (56.0, 56.0));
        assert_eq!(CAPSULE_SIZE, (460.0, 58.0));
    }

    #[test]
    fn cockpit_is_explicit_resizable_and_not_ambient() {
        assert_eq!(
            SurfacePolicy::for_surface("cockpit"),
            SurfacePolicy {
                always_on_top: false,
                resizable: true,
                skip_taskbar: false,
            }
        );
        assert_eq!(
            SurfacePolicy::for_surface("companion"),
            SurfacePolicy {
                always_on_top: true,
                resizable: false,
                skip_taskbar: true,
            }
        );
    }

    #[test]
    fn cockpit_temporarily_replaces_the_companion() {
        let source = include_str!("lib.rs");
        assert!(source.matches("hide_companion(&app)?;").count() > 1);
        assert!(source.matches("restore_companion").count() > 1);
    }
}
