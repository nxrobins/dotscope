pub mod git;
pub mod graph;
pub mod ast;

pub mod mmap;
pub mod ipc;
pub mod daemon;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use graph::TopologicalGraph;

/// Ingest the repository natively in Rust and return the extracted architecture.
#[pyfunction]
fn ingest_repository<'py>(
    py: Python<'py>,
    root: &str,
    max_commits: usize,
    mine_history: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let mut graph = TopologicalGraph::new();

    // Map the local AST tree across Rayon
    graph = ast::build_ast_graph(root, graph);

    if mine_history {
        graph = git::mine_history(root, graph, max_commits).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Git error: {}", e))
        })?;
    }

    // Freeze back to Python FFI bytes
    let result = graph.freeze_to_python(py)?;
    result.set_item("root", root)?;
    result.set_item("commits_analyzed", max_commits)?;
    result.set_item("mined", mine_history)?;

    Ok(result)
}

#[pymodule]
fn dotscope_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ingest_repository, m)?)?;
    Ok(())
}
