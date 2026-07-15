use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use uuid::Uuid;

const MAX_SECRET_BYTES: usize = 10_000;
const MAX_REQUEST_BYTES: u64 = 12_000;
const BROKER_SOCKET_PREFIX: &str = "wf-cred-";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CredentialProvider {
    Minimax,
    Deepseek,
    Moonshot,
    Qwen,
    Zhipu,
    Siliconflow,
    Stepfun,
    Openai,
    Anthropic,
    Composio,
    ProviderContinuations,
}

impl CredentialProvider {
    fn service(self) -> &'static str {
        match self {
            Self::Minimax => "ai.weatherflow.minimax",
            Self::Deepseek => "ai.weatherflow.deepseek",
            Self::Moonshot => "ai.weatherflow.moonshot",
            Self::Qwen => "ai.weatherflow.qwen",
            Self::Zhipu => "ai.weatherflow.zhipu",
            Self::Siliconflow => "ai.weatherflow.siliconflow",
            Self::Stepfun => "ai.weatherflow.stepfun",
            Self::Openai => "ai.weatherflow.openai",
            Self::Anthropic => "ai.weatherflow.anthropic",
            Self::Composio => "ai.weatherflow.composio",
            Self::ProviderContinuations => "ai.weatherflow.provider_continuations",
        }
    }

    fn account(self) -> &'static str {
        match self {
            Self::Composio => "project_api_key",
            Self::ProviderContinuations => "encryption_key_v1",
            _ => "api_key",
        }
    }

    fn renderer_accessible(self) -> bool {
        self != Self::ProviderContinuations
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CredentialStatus {
    pub provider: CredentialProvider,
    pub key_present: bool,
}

#[derive(Debug)]
enum CredentialFailure {
    NotFound,
    Unavailable,
}

trait CredentialBackend: Send + Sync {
    fn set(&self, provider: CredentialProvider, secret: &str) -> Result<(), CredentialFailure>;
    fn delete(&self, provider: CredentialProvider) -> Result<(), CredentialFailure>;
    fn resolve(&self, provider: CredentialProvider) -> Result<String, CredentialFailure>;
}

struct NativeKeychainBackend;

impl NativeKeychainBackend {
    fn entry(provider: CredentialProvider) -> Result<keyring::Entry, CredentialFailure> {
        keyring::Entry::new(provider.service(), provider.account())
            .map_err(|_| CredentialFailure::Unavailable)
    }
}

impl CredentialBackend for NativeKeychainBackend {
    fn set(&self, provider: CredentialProvider, secret: &str) -> Result<(), CredentialFailure> {
        Self::entry(provider)?
            .set_password(secret)
            .map_err(|_| CredentialFailure::Unavailable)
    }

    fn delete(&self, provider: CredentialProvider) -> Result<(), CredentialFailure> {
        match Self::entry(provider)?.delete_credential() {
            Ok(()) => Ok(()),
            Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(CredentialFailure::Unavailable),
        }
    }

    fn resolve(&self, provider: CredentialProvider) -> Result<String, CredentialFailure> {
        match Self::entry(provider)?.get_password() {
            Ok(secret) if !secret.is_empty() && secret.len() <= MAX_SECRET_BYTES => Ok(secret),
            Ok(_) => Err(CredentialFailure::Unavailable),
            Err(keyring::Error::NoEntry) => Err(CredentialFailure::NotFound),
            Err(_) => Err(CredentialFailure::Unavailable),
        }
    }
}

#[derive(Clone)]
pub struct CredentialBrokerConfig {
    pub socket_path: PathBuf,
    token: String,
}

impl std::fmt::Debug for CredentialBrokerConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CredentialBrokerConfig")
            .field("socket_path", &self.socket_path)
            .field("token", &"<redacted>")
            .finish()
    }
}

impl CredentialBrokerConfig {
    pub fn bootstrap_token(&self) -> &str {
        &self.token
    }
}

pub struct CredentialBrokerServer {
    backend: Arc<dyn CredentialBackend>,
    config: CredentialBrokerConfig,
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl CredentialBrokerServer {
    pub fn start_native() -> Result<Self, String> {
        cleanup_stale_broker_sockets();
        Self::start(Arc::new(NativeKeychainBackend), broker_socket_path())
    }

    fn start(backend: Arc<dyn CredentialBackend>, socket_path: PathBuf) -> Result<Self, String> {
        ensure_internal_continuation_key(backend.as_ref())?;
        if socket_path.exists() {
            fs::remove_file(&socket_path).map_err(|_| "credential_socket_unavailable")?;
        }
        let listener =
            UnixListener::bind(&socket_path).map_err(|_| "credential_socket_unavailable")?;
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))
            .map_err(|_| "credential_socket_unavailable")?;
        listener
            .set_nonblocking(true)
            .map_err(|_| "credential_socket_unavailable")?;
        let token = random_token()?;
        let config = CredentialBrokerConfig { socket_path, token };
        let worker_backend = Arc::clone(&backend);
        let worker_config = config.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let worker_stop = Arc::clone(&stop);
        let thread = thread::spawn(move || {
            while !worker_stop.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((stream, _)) => handle_connection(stream, &worker_config, &worker_backend),
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(20));
                    }
                    Err(_) => thread::sleep(Duration::from_millis(20)),
                }
            }
        });
        Ok(Self {
            backend,
            config,
            stop,
            thread: Some(thread),
        })
    }

    pub fn config(&self) -> CredentialBrokerConfig {
        self.config.clone()
    }

    pub fn set(
        &self,
        provider: CredentialProvider,
        secret: &str,
    ) -> Result<CredentialStatus, String> {
        if !provider.renderer_accessible() {
            return Err("credential_forbidden".to_owned());
        }
        if secret.is_empty() || secret.len() > MAX_SECRET_BYTES {
            return Err("credential_invalid".to_owned());
        }
        self.backend
            .set(provider, secret)
            .map_err(|_| "credential_unavailable".to_owned())?;
        Ok(CredentialStatus {
            provider,
            key_present: true,
        })
    }

    pub fn delete(&self, provider: CredentialProvider) -> Result<CredentialStatus, String> {
        if !provider.renderer_accessible() {
            return Err("credential_forbidden".to_owned());
        }
        self.backend
            .delete(provider)
            .map_err(|_| "credential_unavailable".to_owned())?;
        Ok(CredentialStatus {
            provider,
            key_present: false,
        })
    }

    pub fn status(&self, provider: CredentialProvider) -> Result<CredentialStatus, String> {
        if !provider.renderer_accessible() {
            return Err("credential_forbidden".to_owned());
        }
        match self.backend.resolve(provider) {
            Ok(_) => Ok(CredentialStatus {
                provider,
                key_present: true,
            }),
            Err(CredentialFailure::NotFound) => Ok(CredentialStatus {
                provider,
                key_present: false,
            }),
            Err(CredentialFailure::Unavailable) => Err("credential_unavailable".to_owned()),
        }
    }
}

impl Drop for CredentialBrokerServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
        let _ = fs::remove_file(&self.config.socket_path);
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum BrokerOperation {
    Resolve,
}

#[derive(Deserialize)]
struct BrokerRequest {
    operation: BrokerOperation,
    provider: CredentialProvider,
    token: String,
}

#[derive(Serialize)]
struct BrokerResponse<'a> {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    code: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    secret: Option<&'a str>,
}

fn handle_connection(
    mut stream: UnixStream,
    config: &CredentialBrokerConfig,
    backend: &Arc<dyn CredentialBackend>,
) {
    let _ = stream.set_nonblocking(false);
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    let mut request_line = String::new();
    let mut reader = BufReader::new(&stream).take(MAX_REQUEST_BYTES + 1);
    let read = reader.read_line(&mut request_line);
    let response = match read {
        Ok(size) if size > 0 && size as u64 <= MAX_REQUEST_BYTES => {
            match serde_json::from_str::<BrokerRequest>(&request_line) {
                Ok(request) if constant_time_equal(&request.token, &config.token) => {
                    match request.operation {
                        BrokerOperation::Resolve => match backend.resolve(request.provider) {
                            Ok(secret) => write_response(&mut stream, true, None, Some(&secret)),
                            Err(CredentialFailure::NotFound) => {
                                write_response(&mut stream, false, Some("not_found"), None)
                            }
                            Err(CredentialFailure::Unavailable) => {
                                write_response(&mut stream, false, Some("unavailable"), None)
                            }
                        },
                    }
                }
                Ok(_) => write_response(&mut stream, false, Some("unauthorized"), None),
                Err(_) => write_response(&mut stream, false, Some("invalid_request"), None),
            }
        }
        _ => write_response(&mut stream, false, Some("invalid_request"), None),
    };
    let _ = response;
}

fn write_response(
    stream: &mut UnixStream,
    ok: bool,
    code: Option<&str>,
    secret: Option<&str>,
) -> Result<(), ()> {
    serde_json::to_writer(&mut *stream, &BrokerResponse { ok, code, secret }).map_err(|_| ())?;
    stream.write_all(b"\n").map_err(|_| ())
}

fn constant_time_equal(left: &str, right: &str) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.as_bytes()
        .iter()
        .zip(right.as_bytes())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn broker_socket_path() -> PathBuf {
    let nonce = Uuid::new_v4().simple().to_string();
    broker_socket_directory().join(format!(
        "{BROKER_SOCKET_PREFIX}{:x}-{}.sock",
        std::process::id(),
        &nonce[..8]
    ))
}

fn broker_socket_directory() -> PathBuf {
    std::env::temp_dir()
}

fn cleanup_stale_broker_sockets() {
    let Ok(entries) = fs::read_dir(broker_socket_directory()) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if !name.starts_with(BROKER_SOCKET_PREFIX) || !name.ends_with(".sock") {
            continue;
        }
        let owner_pid = name
            .strip_prefix(BROKER_SOCKET_PREFIX)
            .and_then(|value| value.split_once('-'))
            .and_then(|(value, _)| u32::from_str_radix(value, 16).ok());
        if owner_pid == Some(std::process::id()) {
            continue;
        }
        let path = entry.path();
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            continue;
        };
        if metadata.file_type().is_socket() && UnixStream::connect(&path).is_err() {
            let _ = fs::remove_file(path);
        }
    }
}

pub fn random_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "credential_random_unavailable".to_owned())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn ensure_internal_continuation_key(backend: &dyn CredentialBackend) -> Result<(), String> {
    let provider = CredentialProvider::ProviderContinuations;
    match backend.resolve(provider) {
        Ok(secret)
            if secret.len() == 64
                && secret
                    .chars()
                    .all(|character| character.is_ascii_hexdigit()) =>
        {
            Ok(())
        }
        Err(CredentialFailure::NotFound) => {
            let key = random_token()?;
            backend
                .set(provider, &key)
                .map_err(|_| "credential_unavailable".to_owned())
        }
        _ => Err("credential_unavailable".to_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::path::Path;
    use std::sync::Mutex;

    #[derive(Default)]
    struct MemoryBackend {
        values: Mutex<HashMap<CredentialProvider, String>>,
    }

    impl CredentialBackend for MemoryBackend {
        fn set(&self, provider: CredentialProvider, secret: &str) -> Result<(), CredentialFailure> {
            self.values
                .lock()
                .unwrap()
                .insert(provider, secret.to_owned());
            Ok(())
        }

        fn delete(&self, provider: CredentialProvider) -> Result<(), CredentialFailure> {
            self.values.lock().unwrap().remove(&provider);
            Ok(())
        }

        fn resolve(&self, provider: CredentialProvider) -> Result<String, CredentialFailure> {
            self.values
                .lock()
                .unwrap()
                .get(&provider)
                .cloned()
                .ok_or(CredentialFailure::NotFound)
        }
    }

    fn request(path: &Path, value: serde_json::Value) -> serde_json::Value {
        let mut stream = UnixStream::connect(path).unwrap();
        serde_json::to_writer(&mut stream, &value).unwrap();
        stream.write_all(b"\n").unwrap();
        serde_json::from_reader(BufReader::new(stream)).unwrap()
    }

    #[test]
    fn renderer_operations_never_return_secret_material() {
        let backend = Arc::new(MemoryBackend::default());
        let path = broker_socket_path();
        let server = CredentialBrokerServer::start(backend, path).unwrap();

        let set = server
            .set(CredentialProvider::Minimax, "provider-secret")
            .unwrap();
        let status = server.status(CredentialProvider::Minimax).unwrap();

        assert!(set.key_present);
        assert!(status.key_present);
        assert!(!serde_json::to_string(&status)
            .unwrap()
            .contains("provider-secret"));
        assert!(
            !server
                .delete(CredentialProvider::Minimax)
                .unwrap()
                .key_present
        );
    }

    #[test]
    fn foreign_model_providers_are_fixed_renderer_accessible_keychain_items() {
        let backend = Arc::new(MemoryBackend::default());
        let path = broker_socket_path();
        let server = CredentialBrokerServer::start(backend, path).unwrap();

        for provider in [CredentialProvider::Openai, CredentialProvider::Anthropic] {
            let status = server.set(provider, "provider-secret").unwrap();
            assert_eq!(status.provider, provider);
            assert!(status.key_present);
            assert!(server.status(provider).unwrap().key_present);
            assert!(!server.delete(provider).unwrap().key_present);
        }
    }

    #[test]
    fn private_socket_resolves_only_with_launch_token_and_mode_0600() {
        let backend = Arc::new(MemoryBackend::default());
        backend
            .set(CredentialProvider::Minimax, "provider-secret")
            .unwrap();
        let path = broker_socket_path();
        let server = CredentialBrokerServer::start(backend, path.clone()).unwrap();
        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;

        let unauthorized = request(
            &path,
            serde_json::json!({"operation":"resolve","provider":"minimax","token":"0".repeat(64)}),
        );
        let resolved = request(
            &path,
            serde_json::json!({
                "operation":"resolve",
                "provider":"minimax",
                "token":server.config.bootstrap_token(),
            }),
        );

        assert_eq!(mode, 0o600);
        assert_eq!(unauthorized["code"], "unauthorized");
        assert_eq!(resolved["secret"], "provider-secret");
    }

    #[test]
    fn launch_token_contains_256_random_bits() {
        let first = random_token().unwrap();
        let second = random_token().unwrap();

        assert_eq!(first.len(), 64);
        assert!(first.chars().all(|character| character.is_ascii_hexdigit()));
        assert_ne!(first, second);
    }

    #[test]
    fn internal_continuation_key_is_generated_but_renderer_operations_are_denied() {
        let backend = Arc::new(MemoryBackend::default());
        let path = broker_socket_path();
        let server = CredentialBrokerServer::start(backend, path.clone()).unwrap();

        let resolved = request(
            &path,
            serde_json::json!({
                "operation":"resolve",
                "provider":"provider_continuations",
                "token":server.config.bootstrap_token(),
            }),
        );

        assert_eq!(resolved["secret"].as_str().unwrap().len(), 64);
        assert_eq!(
            server
                .set(
                    CredentialProvider::ProviderContinuations,
                    "renderer-controlled"
                )
                .unwrap_err(),
            "credential_forbidden"
        );
        assert_eq!(
            server
                .delete(CredentialProvider::ProviderContinuations)
                .unwrap_err(),
            "credential_forbidden"
        );
        assert_eq!(
            server
                .status(CredentialProvider::ProviderContinuations)
                .unwrap_err(),
            "credential_forbidden"
        );
    }

    #[test]
    fn next_launch_removes_only_unreachable_weatherflow_socket_files() {
        let stale = broker_socket_directory().join(format!(
            "{BROKER_SOCKET_PREFIX}{:x}-{}.sock",
            std::process::id().wrapping_add(1),
            &Uuid::new_v4().simple().to_string()[..8]
        ));
        let listener = UnixListener::bind(&stale).unwrap();
        drop(listener);

        cleanup_stale_broker_sockets();

        assert!(!stale.exists());
    }
}
