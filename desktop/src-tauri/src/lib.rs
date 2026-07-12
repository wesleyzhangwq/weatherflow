mod activity;
mod supervisor;

use std::{process::Command, sync::Mutex};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

const STARTUP_SURFACE: &str = "companion";
const SHORTCUT_SURFACE: &str = "capsule";

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
    WebviewWindowBuilder::new(
        app,
        label,
        WebviewUrl::App(format!("index.html?surface={surface}").into()),
    )
    .title(format!("WeatherFlow {surface}"))
    .initialization_script(initialization_script)
    .inner_size(width, height)
    .decorations(!transparent)
    .transparent(transparent)
    .always_on_top(policy.always_on_top)
    .resizable(policy.resizable)
    .skip_taskbar(policy.skip_taskbar)
    .build()?;
    Ok(())
}

#[tauri::command]
fn open_capsule(app: tauri::AppHandle) -> tauri::Result<()> {
    show_or_create(&app, "capsule", "capsule", 560.0, 82.0, true)
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
    show_or_create(&app, "cockpit", "cockpit", 1100.0, 760.0, false)
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
                            560.0,
                            82.0,
                            true,
                        );
                    }
                })
                .build(),
        )
        .setup(|app| {
            let supervisor =
                supervisor::DaemonSupervisor::start(app.handle()).map_err(std::io::Error::other)?;
            app.manage(Mutex::new(supervisor));
            show_or_create(
                app.handle(),
                STARTUP_SURFACE,
                STARTUP_SURFACE,
                190.0,
                190.0,
                true,
            )?;
            supervisor::monitor(app.handle().clone());
            app.global_shortcut()
                .register("CommandOrControl+Shift+Space")?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_capsule,
            close_capsule,
            open_cockpit,
            choose_workspace_directory,
            supervisor::daemon_bridge,
            supervisor::restart_daemon,
            activity::sample_activity_metadata
        ])
        .run(tauri::generate_context!())
        .expect("WeatherFlow desktop shell failed");
}

#[cfg(test)]
mod tests {
    use super::{SurfacePolicy, SHORTCUT_SURFACE, STARTUP_SURFACE};

    #[test]
    fn startup_and_shortcut_never_auto_open_cockpit() {
        assert_eq!(STARTUP_SURFACE, "companion");
        assert_eq!(SHORTCUT_SURFACE, "capsule");
        assert_ne!(STARTUP_SURFACE, "cockpit");
        assert_ne!(SHORTCUT_SURFACE, "cockpit");
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
}
