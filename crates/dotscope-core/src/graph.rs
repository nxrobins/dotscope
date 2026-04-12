use petgraph::graph::{NodeIndex, UnGraph};
use petgraph::visit::EdgeRef;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::collections::HashMap;

// The pure Rust graph object, decoupled from Python completely during the build phase.
pub struct TopologicalGraph {
    pub graph: UnGraph<String, u32>,
    pub name_to_id: HashMap<String, NodeIndex>,
}

impl TopologicalGraph {
    pub fn new() -> Self {
        Self {
            graph: UnGraph::new_undirected(),
            name_to_id: HashMap::new(),
        }
    }

    pub fn get_or_insert(&mut self, name: &str) -> NodeIndex {
        if let Some(&idx) = self.name_to_id.get(name) {
            idx
        } else {
            let idx = self.graph.add_node(name.to_string());
            self.name_to_id.insert(name.to_string(), idx);
            idx
        }
    }

    pub fn add_edge_weight(&mut self, source: NodeIndex, target: NodeIndex, weight: u32) {
        if let Some(edge_idx) = self.graph.find_edge(source, target) {
            if let Some(w) = self.graph.edge_weight_mut(edge_idx) {
                *w += weight;
            }
        } else {
            self.graph.add_edge(source, target, weight);
        }
    }

    pub fn get_raw_tensors(&self) -> (Vec<u8>, Vec<u8>, Vec<u8>, Vec<String>) {
        let mut node_names = Vec::new();
        for node in self.graph.node_weights() {
            node_names.push(node.clone());
        }

        let edge_count = self.graph.edge_count();
        let mut sources = Vec::with_capacity(edge_count);
        let mut targets = Vec::with_capacity(edge_count);
        let mut weights = Vec::with_capacity(edge_count);

        for edge in self.graph.edge_references() {
            sources.push(edge.source().index() as u32);
            targets.push(edge.target().index() as u32);
            weights.push(*edge.weight());
        }

        let sources_bytes = unsafe {
            std::slice::from_raw_parts(sources.as_ptr() as *const u8, sources.len() * 4)
        }.to_vec();
        
        let targets_bytes = unsafe {
            std::slice::from_raw_parts(targets.as_ptr() as *const u8, targets.len() * 4)
        }.to_vec();
        
        let weights_bytes = unsafe {
            std::slice::from_raw_parts(weights.as_ptr() as *const u8, weights.len() * 4)
        }.to_vec();

        (sources_bytes, targets_bytes, weights_bytes, node_names)
    }

    /// Freezes the graph and packages it into pure C-contiguous `PyBytes` objects for Python
    pub fn freeze_to_python<'py>(self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let result = PyDict::new(py);

        // Nodes map to a standard list since string IDs natively deserialize quickly
        // and we need them for display lookup bounds anyway.
        let node_names = PyList::empty(py);
        for node in self.graph.node_weights() {
            node_names.append(node)?;
        }
        result.set_item("node_names", node_names)?;

        let edge_count = self.graph.edge_count();
        let mut sources = Vec::with_capacity(edge_count);
        let mut targets = Vec::with_capacity(edge_count);
        let mut weights = Vec::with_capacity(edge_count);

        for edge in self.graph.edge_references() {
            sources.push(edge.source().index() as u32);
            targets.push(edge.target().index() as u32);
            weights.push(*edge.weight());
        }

        // Convert the u32 vectors into raw bytes directly mapped from memory
        // This is safe because we are transmuting [u32] to [u8] statically, generating zero-copy arrays
        let sources_bytes = unsafe {
            std::slice::from_raw_parts(sources.as_ptr() as *const u8, sources.len() * 4)
        };
        let targets_bytes = unsafe {
            std::slice::from_raw_parts(targets.as_ptr() as *const u8, targets.len() * 4)
        };
        let weights_bytes = unsafe {
            std::slice::from_raw_parts(weights.as_ptr() as *const u8, weights.len() * 4)
        };

        // Pass gravity scores directly from petgraph FFI
        let mut gravity = Vec::with_capacity(self.graph.node_count());
        for node_idx in self.graph.node_indices() {
             gravity.push(self.graph.edges_directed(node_idx, petgraph::Direction::Incoming).count() as u32);
        }
        let gravity_bytes = unsafe {
             std::slice::from_raw_parts(gravity.as_ptr() as *const u8, gravity.len() * 4)
        };

        result.set_item("edge_sources", PyBytes::new(py, sources_bytes))?;
        result.set_item("edge_targets", PyBytes::new(py, targets_bytes))?;
        result.set_item("edge_weights", PyBytes::new(py, weights_bytes))?;
        result.set_item("node_gravity_scores", PyBytes::new(py, gravity_bytes))?;

        Ok(result)
    }
}
