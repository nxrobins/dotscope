use std::sync::Arc;
use std::sync::mpsc::channel;
use std::time::Duration;
use notify::{Watcher, RecursiveMode, EventKind};
use crate::mmap::{ControlPlane, TopologyBuffer};
use crate::{ast, graph::TopologicalGraph};
use std::path::{Path, PathBuf};
use std::collections::HashSet;

pub fn run_watcher(root: String, dotscope_dir: PathBuf, control: Arc<ControlPlane>) {
    let (tx, rx) = channel();

    // Create watcher
    let mut watcher = notify::recommended_watcher(move |res: Result<notify::Event, notify::Error>| {
        if let Ok(event) = res {
            // We only care about file modifications that indicate a save
            if matches!(event.kind, EventKind::Modify(_) | EventKind::Create(_) | EventKind::Remove(_)) {
                for path in event.paths {
                    if let Some(ext) = path.extension() {
                        let ext_str = ext.to_string_lossy();
                        if ext_str == "py" || ext_str == "ts" || ext_str == "js" || ext_str == "rs" || ext_str == "go" {
                            let _ = tx.send(path);
                        }
                    }
                }
            }
        }
    }).unwrap();

    watcher.watch(Path::new(&root), RecursiveMode::Recursive).unwrap();
    println!("Dotscope Daemon watching {}", root);

    // Initial load
    println!("Running initial ingestion...");
    control.mark_dirty();
    trigger_ingest(&root, &dotscope_dir, &control);
    control.mark_clean();
    println!("Initial ingestion complete.");

    // Debounce loop (Token Bucket)
    let mut dirty_paths: HashSet<PathBuf> = HashSet::new();

    loop {
        // Wait for the first event infinitely
        if dirty_paths.is_empty() {
            if let Ok(path) = rx.recv() {
                dirty_paths.insert(path);
            }
        }
        
        // Once we have a dirty path, we wait for silence (200ms)
        let debounce_window = Duration::from_millis(200);
        let mut silence_broken = true;

        while silence_broken {
            if let Ok(path) = rx.recv_timeout(debounce_window) {
                dirty_paths.insert(path);
            } else {
                // Timeout reached, we had 200ms of absolute silence!
                silence_broken = false;
            }
        }

        // Fire ingestion!
        if !dirty_paths.is_empty() {
            println!("Triggering ingestion for {} modified files...", dirty_paths.len());
            control.mark_dirty();
            trigger_ingest(&root, &dotscope_dir, &control);
            dirty_paths.clear();
            control.mark_clean();
        }
    }
}

fn trigger_ingest(root: &str, dotscope_dir: &Path, control: &ControlPlane) {
    let mut graph = TopologicalGraph::new();
    graph = ast::build_ast_graph(root, graph);
    
    // We do NOT mine history here for real-time daemon, we just do structure
    let (sources, targets, weights, nodes) = graph.get_raw_tensors();
    
    // Determine the inactive buffer
    let active = control.header().active_buffer.load(std::sync::atomic::Ordering::SeqCst);
    let target_buffer_id = if active == 0 { 1 } else { 0 };
    
    let buffer = TopologyBuffer::new(dotscope_dir, target_buffer_id);
    buffer.write_payload(&sources, &targets, &weights).expect("Failed to write AST buffer");
    
    // Also save the nodes struct as json for Python to read easily
    let manifest_path = dotscope_dir.join("structural_manifest.json");
    let manifest_json = format!("{{\"nodes\": {:?}, \"commits_analyzed\": 0}}", nodes);
    std::fs::write(manifest_path, manifest_json).unwrap();
    
    // Flip Epoch Buffer
    let new_active = control.flip_buffer();
    println!("Flipped commit A/B buffer to {}", new_active);
}
