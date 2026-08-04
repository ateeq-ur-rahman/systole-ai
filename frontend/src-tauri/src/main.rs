// Systole AI - Storage Manager
// Tauri desktop shell entrypoint.
//
// Responsibility: launch the bundled Python backend (run.py / the frozen
// systole-service.exe produced by the build scripts) as a child process
// when the app window opens, and terminate it cleanly on exit. The
// webview itself only talks to the backend over HTTP (see
// frontend/src/api/client.ts) -- this file does no business logic.

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct BackendProcess(Mutex<Option<Child>>);

/// Writes a plain-text diagnostic file describing exactly what happened
/// during backend startup. Deliberately NOT relying on a console or a
/// dialog plugin (can't verify either compiles/behaves correctly without
/// a real Windows build to test against) -- a file on disk is the one
/// mechanism guaranteed to work and be inspectable after the fact,
/// regardless of whether the app has a console or not.
fn write_startup_log(app_data_dir: &Path, message: &str) {
    let _ = std::fs::create_dir_all(app_data_dir);
    let log_path = app_data_dir.join("startup-diagnostic.log");
    let _ = std::fs::write(&log_path, message);
}

/// Recursively searches under `root` for a file named `filename`,
/// returning the first match. Used as a robustness net: rather than
/// betting the whole app on one or two guessed paths for where Tauri's
/// bundler places a declared resource (a detail that's genuinely hard to
/// verify without a real Windows build to test against), this finds it
/// wherever it actually landed. Resource directories are small (a
/// handful of icon files plus this one executable), so a full recursive
/// walk is cheap and not a performance concern.
fn find_file(root: &Path, filename: &str) -> Option<PathBuf> {
    let entries = std::fs::read_dir(root).ok()?;
    let mut subdirs = Vec::new();

    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            subdirs.push(path);
        } else if path.file_name().map(|n| n == filename).unwrap_or(false) {
            return Some(path);
        }
    }

    for dir in subdirs {
        if let Some(found) = find_file(&dir, filename) {
            return Some(found);
        }
    }

    None
}

fn spawn_backend(resource_dir: &Path, app_data_dir: &Path) -> Option<Child> {
    let service_path = match find_file(resource_dir, "systole-service.exe") {
        Some(path) => path,
        None => {
            write_startup_log(
                app_data_dir,
                &format!(
                    "Systole AI could not start its background service.\n\n\
                     Reason: systole-service.exe was not found anywhere under the \
                     app's resource directory.\n\n\
                     Resource directory searched: {:?}\n\n\
                     This means the backend executable either wasn't bundled into \
                     this installer correctly, or landed in a location this search \
                     didn't expect. If you're seeing this, please share this file's \
                     full contents for debugging.",
                    resource_dir
                ),
            );
            return None;
        }
    };

    match Command::new(&service_path).spawn() {
        Ok(child) => {
            write_startup_log(
                app_data_dir,
                &format!("Systole AI background service started successfully.\nLaunched: {:?}", service_path),
            );
            Some(child)
        }
        Err(e) => {
            write_startup_log(
                app_data_dir,
                &format!(
                    "Systole AI found the background service but failed to launch it.\n\n\
                     Path found: {:?}\nError: {e}",
                    service_path
                ),
            );
            None
        }
    }
}

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let resource_dir = app
                .path()
                .resource_dir()
                .expect("failed to resolve resource dir");
            let app_data_dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| resource_dir.clone());
            let child = spawn_backend(&resource_dir, &app_data_dir);
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
