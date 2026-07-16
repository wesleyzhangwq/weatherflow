use core_foundation::base::TCFType;
use core_foundation::string::CFString;
use core_foundation_sys::base::{CFGetTypeID, CFTypeRef};
use core_foundation_sys::string::{CFStringGetTypeID, CFStringRef};
use objc2_app_kit::NSWorkspace;
use serde::Serialize;
use std::ffi::c_void;

type AXUIElementRef = *const c_void;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrusted() -> u8;
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> i32;
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventSourceSecondsSinceLastEventType(state_id: u32, event_type: u32) -> f64;
}

#[derive(Serialize)]
pub struct ActivitySample {
    pub idle_seconds: u64,
    pub app_name: String,
    pub bundle_id: String,
    pub window_title: Option<String>,
    pub focused: bool,
    pub idle_state: &'static str,
    pub category: &'static str,
    pub accessibility: &'static str,
}

#[tauri::command]
pub fn sample_activity_metadata() -> Result<ActivitySample, String> {
    let workspace = NSWorkspace::sharedWorkspace();
    let application = workspace
        .frontmostApplication()
        .ok_or_else(|| "frontmost_application_unavailable".to_owned())?;
    let app_name = application
        .localizedName()
        .map(|value| value.to_string())
        .unwrap_or_else(|| "Unknown Application".to_owned());
    let pid = application.processIdentifier();
    let bundle_id = application
        .bundleIdentifier()
        .map(|value| value.to_string())
        .unwrap_or_else(|| format!("unknown.pid.{pid}"));
    let idle_seconds = idle_seconds();
    let accessibility_granted = accessibility_is_granted();
    let window_title = accessibility_granted
        .then(|| focused_window_title(pid))
        .flatten();
    let category = category_for_application(&app_name);
    Ok(ActivitySample {
        idle_seconds,
        app_name,
        bundle_id,
        window_title,
        focused: true,
        idle_state: if idle_seconds >= 60 { "idle" } else { "active" },
        category,
        accessibility: if accessibility_granted {
            "granted"
        } else {
            "denied"
        },
    })
}

fn idle_seconds() -> u64 {
    // Combined-session + any-input is the native Quartz equivalent of system idle time.
    unsafe { CGEventSourceSecondsSinceLastEventType(0, u32::MAX).max(0.0) as u64 }
}

fn accessibility_is_granted() -> bool {
    unsafe { AXIsProcessTrusted() != 0 }
}

fn focused_window_title(pid: i32) -> Option<String> {
    unsafe {
        // AX attribute names are stable CFString values, but the corresponding
        // kAX* constants are not exported as linkable symbols on every macOS
        // SDK/runtime combination.
        let focused_window_attribute = CFString::new("AXFocusedWindow");
        let title_attribute = CFString::new("AXTitle");
        let application = AXUIElementCreateApplication(pid);
        if application.is_null() {
            return None;
        }
        let application =
            core_foundation::base::CFType::wrap_under_create_rule(application as CFTypeRef);
        let mut window: CFTypeRef = std::ptr::null();
        if AXUIElementCopyAttributeValue(
            application.as_CFTypeRef() as AXUIElementRef,
            focused_window_attribute.as_concrete_TypeRef(),
            &mut window,
        ) != 0
            || window.is_null()
        {
            return None;
        }
        let window = core_foundation::base::CFType::wrap_under_create_rule(window);
        let mut title: CFTypeRef = std::ptr::null();
        if AXUIElementCopyAttributeValue(
            window.as_CFTypeRef() as AXUIElementRef,
            title_attribute.as_concrete_TypeRef(),
            &mut title,
        ) != 0
            || title.is_null()
        {
            return None;
        }
        if CFGetTypeID(title) != CFStringGetTypeID() {
            let _ = core_foundation::base::CFType::wrap_under_create_rule(title);
            return None;
        }
        let title = CFString::wrap_under_create_rule(title as CFStringRef).to_string();
        (!title.is_empty()).then_some(title)
    }
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
    fn serialized_sample_contains_complete_window_identity_and_permission_state() {
        let json = serde_json::to_string(&ActivitySample {
            idle_seconds: 3,
            app_name: "Visual Studio Code".to_owned(),
            bundle_id: "com.microsoft.VSCode".to_owned(),
            window_title: Some("activity.rs — WeatherFlow".to_owned()),
            focused: true,
            idle_state: "active",
            category: "development",
            accessibility: "granted",
        })
        .unwrap();
        assert!(json.contains(r#""app_name":"Visual Studio Code""#));
        assert!(json.contains(r#""bundle_id":"com.microsoft.VSCode""#));
        assert!(json.contains(r#""window_title":"activity.rs — WeatherFlow""#));
        assert!(json.contains(r#""accessibility":"granted""#));
    }
}
