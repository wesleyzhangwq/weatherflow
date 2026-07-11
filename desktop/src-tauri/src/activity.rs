use serde::Serialize;
use std::process::Command;

#[derive(Serialize)]
pub struct ActivitySample {
    pub idle_seconds: u64,
    pub category: &'static str,
}

#[tauri::command]
pub fn sample_activity_metadata() -> ActivitySample {
    let idle_seconds = idle_seconds().unwrap_or(0);
    let category = frontmost_application()
        .as_deref()
        .map(category_for_application)
        .unwrap_or("other");
    ActivitySample {
        idle_seconds,
        category,
    }
}

fn idle_seconds() -> Option<u64> {
    let output = Command::new("ioreg")
        .args(["-c", "IOHIDSystem"])
        .output()
        .ok()?;
    let text = String::from_utf8(output.stdout).ok()?;
    let marker = "\"HIDIdleTime\" = ";
    let value = text.lines().find_map(|line| {
        let raw = line.split_once(marker)?.1.trim();
        raw.parse::<u64>().ok()
    })?;
    Some(value / 1_000_000_000)
}

fn frontmost_application() -> Option<String> {
    let output = Command::new("osascript")
        .args([
            "-e",
            "tell application \"System Events\" to get name of first process whose frontmost is true",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8(output.stdout)
        .ok()
        .map(|value| value.trim().to_string())
}

fn category_for_application(application: &str) -> &'static str {
    let value = application.to_lowercase();
    if ["xcode", "visual studio code", "terminal", "iterm", "warp"]
        .iter()
        .any(|name| value.contains(name))
    {
        "development"
    } else if ["slack", "mail", "messages", "zoom", "teams"]
        .iter()
        .any(|name| value.contains(name))
    {
        "communication"
    } else if ["safari", "chrome", "firefox", "arc"]
        .iter()
        .any(|name| value.contains(name))
    {
        "research"
    } else if ["calendar", "notion", "reminders"]
        .iter()
        .any(|name| value.contains(name))
    {
        "planning"
    } else if ["figma", "sketch", "photoshop"]
        .iter()
        .any(|name| value.contains(name))
    {
        "creative"
    } else {
        "other"
    }
}

#[cfg(test)]
mod tests {
    use super::{category_for_application, ActivitySample};

    #[test]
    fn raw_application_identity_maps_to_coarse_category() {
        assert_eq!(
            category_for_application("Visual Studio Code"),
            "development"
        );
        assert_eq!(category_for_application("Slack"), "communication");
        assert_eq!(category_for_application("Unknown Secret Editor"), "other");
    }

    #[test]
    fn serialized_sample_contains_no_raw_identity() {
        let json = serde_json::to_string(&ActivitySample {
            idle_seconds: 3,
            category: "development",
        })
        .unwrap();
        assert_eq!(json, r#"{"idle_seconds":3,"category":"development"}"#);
    }
}
