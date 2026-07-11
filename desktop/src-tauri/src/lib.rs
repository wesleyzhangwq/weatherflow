use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

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
    WebviewWindowBuilder::new(
        app,
        label,
        WebviewUrl::App(format!("index.html?surface={surface}").into()),
    )
    .title(format!("WeatherFlow {surface}"))
    .inner_size(width, height)
    .decorations(!transparent)
    .transparent(transparent)
    .always_on_top(surface != "cockpit")
    .resizable(surface == "cockpit")
    .skip_taskbar(surface != "cockpit")
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

pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        let _ = show_or_create(app, "capsule", "capsule", 560.0, 82.0, true);
                    }
                })
                .build(),
        )
        .setup(|app| {
            app.global_shortcut().register("CommandOrControl+Shift+Space")?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_capsule,
            close_capsule,
            open_cockpit
        ])
        .run(tauri::generate_context!())
        .expect("WeatherFlow desktop shell failed");
}
