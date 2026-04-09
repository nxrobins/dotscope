use std::net::TcpListener;
use std::io::{Read, Write};
use std::sync::Arc;
use std::time::Duration;
use std::thread;
use crate::mmap::ControlPlane;

pub fn start_ipc_server(port: u16, control: Arc<ControlPlane>) {
    let listener = TcpListener::bind(format!("127.0.0.1:{}", port)).expect("Failed to bind IPC port");
    println!("Dotscope IPC Server listening on 127.0.0.1:{}", port);

    for stream in listener.incoming() {
        if let Ok(mut stream) = stream {
            let mut control_ref = control.clone();
            
            // Simple blocking thread per connection
            thread::spawn(move || {
                let mut buf = [0; 1024];
                if let Ok(size) = stream.read(&mut buf) {
                    let req = String::from_utf8_lossy(&buf[..size]).to_string();
                    
                    // The agent asks for {"consistency": "strong"}
                    if req.contains("strong") {
                        // MVCC Strict Consistency: Wait for the write-plane to unlock
                        let mut backoff = 10;
                        while control_ref.header().dirty_flag.load(std::sync::atomic::Ordering::SeqCst) == 1 {
                            thread::sleep(Duration::from_millis(backoff));
                            if backoff < 200 {
                                backoff += 10;
                            }
                        }
                    } else if req.contains("ping") {
                        let _ = stream.write_all(b"pong");
                        return;
                    }
                    
                    // Return the currently committed state ID
                    let epoch = control_ref.header().epoch_version.load(std::sync::atomic::Ordering::SeqCst);
                    let active = control_ref.header().active_buffer.load(std::sync::atomic::Ordering::SeqCst);
                    
                    let response = format!("{{\"status\":\"ready\",\"epoch\":{},\"active_buffer\":{}}}", epoch, active);
                    let _ = stream.write_all(response.as_bytes());
                }
            });
        }
    }
}
