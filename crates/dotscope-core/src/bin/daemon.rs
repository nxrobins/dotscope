use std::env;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;

use dotscope_core::mmap::ControlPlane;
use dotscope_core::ipc::start_ipc_server;
use dotscope_core::daemon::run_watcher;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        println!("Usage: dotscope_daemon <root_path> <port>");
        std::process::exit(1);
    }

    let root = args[1].clone();
    let port: u16 = args[2].parse().expect("Invalid port number");

    let root_path = PathBuf::from(&root);
    let dotscope_dir = root_path.join(".dotscope");
    std::fs::create_dir_all(&dotscope_dir).expect("Failed to create .dotscope directory");

    let control = Arc::new(ControlPlane::new(&dotscope_dir).expect("Failed to initialize mmap control plane"));

    // Spawn IPC server
    let control_ipc = control.clone();
    thread::spawn(move || {
        start_ipc_server(port, control_ipc);
    });

    // Run the watcher in the main thread
    run_watcher(root, dotscope_dir, control);
}
