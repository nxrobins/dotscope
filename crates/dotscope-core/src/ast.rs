use crate::graph::TopologicalGraph;
use ignore::WalkBuilder;
use rayon::prelude::*;
use std::fs;
use std::sync::Arc;
use tree_sitter::{Parser, Query, QueryCursor, Language};

struct GlobalQueries {
    python: Arc<Query>,
    rust: Arc<Query>,
    js: Arc<Query>,
}

fn load_global_queries() -> GlobalQueries {
    let python_lang = tree_sitter_python::language();
    let python_query = Query::new(&python_lang, "(import_statement name: (_) @import)")
        .expect("Failed to compile Python import query");

    let rust_lang = tree_sitter_rust::language();
    let rust_query = Query::new(&rust_lang, "(use_declaration argument: (_) @import)")
        .expect("Failed to compile Rust import query");

    let js_lang = tree_sitter_javascript::language();
    let js_query = Query::new(&js_lang, "(import_statement source: (_) @import)")
        .expect("Failed to compile JS import query");

    GlobalQueries {
        python: Arc::new(python_query),
        rust: Arc::new(rust_query),
        js: Arc::new(js_query),
    }
}

pub fn build_ast_graph(root: &str, mut graph: TopologicalGraph) -> TopologicalGraph {
    let queries = load_global_queries();

    let mut builder = WalkBuilder::new(root);
    builder.hidden(false).git_ignore(true);
    let walker = builder.build();

    let mut files = Vec::new();
    for result in walker {
        if let Ok(entry) = result {
            if entry.file_type().map(|f| f.is_file()).unwrap_or(false) {
                if let Some(ext) = entry.path().extension() {
                    let ext_str = ext.to_str().unwrap_or("");
                    if ext_str == "rs" || ext_str == "py" || ext_str == "js" {
                        files.push((entry.path().to_path_buf(), ext_str.to_string()));
                    }
                }
            }
        }
    }

    // Rayon maps over files concurrently. Isolated parsing preventing GIL block and CPU cache line overrides
    let parsed_files: Vec<_> = files.par_iter().filter_map(|(path, ext)| {
        let content = fs::read_to_string(path).unwrap_or_default();
        let mut parser = Parser::new();
        let mut cursor = QueryCursor::new();
        
        let mut imports = Vec::new();

        if ext == "py" {
            parser.set_language(&tree_sitter_python::language()).unwrap();
            if let Some(tree) = parser.parse(&content, None) {
                let matches = cursor.matches(&queries.python, tree.root_node(), content.as_bytes());
                for m in matches {
                    for cap in m.captures {
                        if let Ok(text) = cap.node.utf8_text(content.as_bytes()) {
                            imports.push(text.to_string());
                        }
                    }
                }
            }
        } else if ext == "rs" {
            parser.set_language(&tree_sitter_rust::language()).unwrap();
            if let Some(tree) = parser.parse(&content, None) {
                let matches = cursor.matches(&queries.rust, tree.root_node(), content.as_bytes());
                for m in matches {
                    for cap in m.captures {
                        if let Ok(text) = cap.node.utf8_text(content.as_bytes()) {
                            imports.push(text.to_string());
                        }
                    }
                }
            }
        } else if ext == "js" {
            parser.set_language(&tree_sitter_javascript::language()).unwrap();
            if let Some(tree) = parser.parse(&content, None) {
                let matches = cursor.matches(&queries.js, tree.root_node(), content.as_bytes());
                for m in matches {
                    for cap in m.captures {
                        if let Ok(text) = cap.node.utf8_text(content.as_bytes()) {
                            imports.push(text.to_string());
                        }
                    }
                }
            }
        }

        Some((path.to_string_lossy().to_string(), imports))
    }).collect();

    // Map synchronous topological graph resolution outside rayon thread map
    for (src_path, imports) in parsed_files {
        let source = graph.get_or_insert(&src_path);
        for imp in imports {
            let target = graph.get_or_insert(&imp);
            graph.add_edge_weight(source, target, 1);
        }
    }

    graph
}
