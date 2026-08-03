// Systole AI - Storage Manager
// Tauri desktop shell entrypoint.
//
// Responsibility: launch the bundled Python backend (run.py / the frozen
// systole-service.exe produced by the build scripts) as a child process
// when the app window opens, and terminate it cleanly on exit. The
// webview itself only talks to the backend over HTTP (see
// frontend/src/api/client.ts) -- this file does no business logic.

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct BackendProcess(Mutex<Option<Child>>);

fn spawn_backend(resource_dir: &std::path::Path) -> Option<Child> {
    // Tauri's bundler copies files declared under bundle.resources into
    // the installed app's resource directory. We check the direct path
    // first (the expected location for a bare filename resource), with
    // a resources/ subfolder as a fallback in case that assumption is
    // ever wrong for a given Tauri version -- cheap insurance against a
    // detail that's hard to verify without a real Windows build to test.
    let candidates = [
        resource_dir.join("systole-service.exe"),
        resource_dir.join("resources").join("systole-service.exe"),
    ];

    let service_path = candidates.iter().find(|p| p.exists());

    let Some(service_path) = service_path else {
        eprintln!(
            "systole-service.exe not found in any expected location under {:?}; is the backend running separately?",
            resource_dir
        );
        return None;
    };

    Command::new(service_path)
        .spawn()
        .map_err(|e| eprintln!("Failed to launch Systole backend: {e}"))
        .ok()
}

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let resource_dir = app
                .path()
                .resource_dir()
                .expect("failed to resolve resource dir");
            let child = spawn_backend(&resource_dir);
            let state = app.state::<BackendProcess>();
            *state.0.lock().unwrap() = child;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<BackendProcess>();
                let mut guard = state.0.lock().unwrap();
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Systole");
}
