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
///
/// Written to the OS temp directory specifically, NOT app_data_dir --
/// temp is guaranteed writable by any user account with no special
/// permissions, whereas an MSI install commonly lands under
/// C:\Program Files\, and if Tauri's app_data_dir() resolution were to
/// ever fail and fall back to a location under there, a non-admin
/// process couldn't write to it at all, silently defeating the entire
/// point of this diagnostic.
fn write_startup_log(message: &str) {
    let log_path = std::env::temp_dir().join("systole-startup-diagnostic.log");
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

fn spawn_backend(resource_dir: &Path) -> Option<Child> {
    let service_path = match find_file(resource_dir, "systole-service.exe") {
        Some(path) => path,
        None => {
            write_startup_log(&format!(
                "Systole AI could not start its background service.\n\n\
                 Reason: systole-service.exe was not found anywhere under the \
                 app's resource directory.\n\n\
                 Resource directory searched: {:?}\n\n\
                 This means the backend executable either wasn't bundled into \
                 this installer correctly, or landed in a location this search \
                 didn't expect. If you're seeing this, please share this file's \
                 full contents for debugging.",
                resource_dir
            ));
            return None;
        }
    };

    // The child process's own stdout/stderr are NOT the same thing as
    // this diagnostic log. By default, Command::spawn() has the child
    // inherit the parent's stdio handles -- and this parent is a
    // --windowed app with no console, so those handles are likely
    // None/invalid for the child too. That means any Python-level
    // output or crash traceback OTHER than the one specific exception
    // already fixed in logging_config.py has been silently discarded
    // this whole time, which is exactly why "the process launched
    // successfully" told us nothing about what happened next.
    // Redirecting to real files closes that blind spot.
    let temp_dir = std::env::temp_dir();
    let stdout_path = temp_dir.join("systole-backend-stdout.log");
    let stderr_path = temp_dir.join("systole-backend-stderr.log");

    let stdout_file = std::fs::File::create(&stdout_path);
    let stderr_file = std::fs::File::create(&stderr_path);

    let mut cmd = Command::new(&service_path);
    if let Ok(f) = stdout_file {
        cmd.stdout(std::process::Stdio::from(f));
    }
    if let Ok(f) = stderr_file {
        cmd.stderr(std::process::Stdio::from(f));
    }

    match cmd.spawn() {
        Ok(child) => {
            write_startup_log(&format!(
                "Systole AI background service started successfully.\n\
                 Launched: {:?}\n\
                 Process ID: {}\n\n\
                 If the app still can't reach the backend, check these two files \
                 for what happened after launch:\n  {:?}\n  {:?}",
                service_path, child.id(), stdout_path, stderr_path
            ));
            Some(child)
        }
        Err(e) => {
            write_startup_log(&format!(
                "Systole AI found the background service but failed to launch it.\n\n\
                 Path found: {:?}\nError: {e}",
                service_path
            ));
            None
        }
    }
}

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            // resource_dir() itself can fail. It previously used
            // .expect(), which panics -- and a panic in a --windowed
            // build produces no visible output at all (no console, no
            // dialog), leaving zero diagnostic trail. Handling it
            // explicitly means even THIS failure mode gets written to
            // the log, instead of the app just vanishing with no trace.
            let resource_dir = match app.path().resource_dir() {
                Ok(dir) => dir,
                Err(e) => {
                    write_startup_log(&format!(
                        "Systole AI failed to resolve its own resource directory at startup.\n\
                         Error: {e}\n\n\
                         This is a Tauri-level failure before the backend was even searched for."
                    ));
                    return Ok(()); // let the window still open so the frontend's
                                    // own "can't reach service" message shows,
                                    // rather than the whole app failing to launch
                }
            };

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
