use crate::graph::TopologicalGraph;
use ignore::WalkBuilder;
use rayon::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tree_sitter::{Parser, Query, QueryCursor, Language};
use regex::Regex;
use lazy_static::lazy_static;

lazy_static! {
    static ref HEURISTIC_REGEX: Regex = Regex::new(
        r#"(?:#include\s*[<"]([^>"]+)[>"])|(?:using\s+([^;]+);)|(?:require\s*\(\s*['"]([^'"]+)['"]\))|(?:import\s+['"]([^'"]+)['"])|(?:from\s+([^\s]+)\s+import)"#
    ).expect("Failed to compile heuristic Regex matrix");
}

struct GlobalQueries {
    python: Arc<Query>,
    rust: Arc<Query>,
    js: Arc<Query>,
    ts: Arc<Query>,
    java: Arc<Query>,
    go: Arc<Query>,
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

    let ts_lang = tree_sitter_typescript::language_typescript();
    let ts_query = Query::new(&ts_lang, "(import_statement source: (_) @import)")
        .expect("Failed to compile TS import query");

    let java_lang = tree_sitter_java::language();
    let java_query = Query::new(&java_lang, "(import_declaration (scoped_identifier) @import)")
        .expect("Failed to compile Java import query");

    let go_lang = tree_sitter_go::language();
    let go_query = Query::new(&go_lang, "(import_spec path: (interpreted_string_literal) @import)")
        .expect("Failed to compile Go import query");

    GlobalQueries {
        python: Arc::new(python_query),
        rust: Arc::new(rust_query),
        js: Arc::new(js_query),
        ts: Arc::new(ts_query),
        java: Arc::new(java_query),
        go: Arc::new(go_query),
    }
}

// Set of files we consider 'Dark Matter' — we run the regex heuristic on these.
fn is_dark_matter_ext(ext: &str) -> bool {
    matches!(ext, "cs" | "cpp" | "c" | "rb" | "php" | "swift" | "kt" | "sol" | "tsx" | "jsx")
}

fn clean_heuristic_path(base_dir: &Path, raw: &str) -> String {
    let mut resolved = base_dir.to_path_buf();
    for part in raw.split('/') {
        if part == "." { continue; }
        if part == ".." {
            resolved.pop();
        } else {
            resolved.push(part);
        }
    }
    resolved.to_string_lossy().replace("\\", "/").to_string()
}

pub fn build_ast_graph(root: &str, mut graph: TopologicalGraph) -> TopologicalGraph {
    let queries = load_global_queries();

    let mut builder = WalkBuilder::new(root);
    builder.hidden(false).git_ignore(true);
    let walker = builder.build();

    let mut files = Vec::new();
    let mut known_files = HashSet::new();

    for result in walker {
        if let Ok(entry) = result {
            if entry.file_type().map(|f| f.is_file()).unwrap_or(false) {
                if let Some(ext) = entry.path().extension() {
                    let ext_str = ext.to_str().unwrap_or("");
                    let path_buf = entry.path().to_path_buf();
                    // We only process native ASTs OR dark matter extensions
                    if matches!(ext_str, "rs" | "py" | "js" | "ts" | "java" | "go") || is_dark_matter_ext(ext_str) {
                        let normalized = path_buf.to_string_lossy().replace("\\", "/");
                        known_files.insert(normalized);
                        files.push((path_buf, ext_str.to_string()));
                    }
                }
            }
        }
    }

    // Rayon maps over files concurrently.
    let parsed_files: Vec<_> = files.par_iter().filter_map(|(path, ext)| {
        let content = fs::read_to_string(path).unwrap_or_default();
        let mut imports = Vec::new();

        if ext == "py" || ext == "rs" || ext == "js" || ext == "ts" || ext == "java" || ext == "go" {
            let mut parser = Parser::new();
            let mut cursor = QueryCursor::new();
            
            let query = match ext.as_str() {
                "py" => { parser.set_language(&tree_sitter_python::language()).unwrap(); &queries.python },
                "rs" => { parser.set_language(&tree_sitter_rust::language()).unwrap(); &queries.rust },
                "js" => { parser.set_language(&tree_sitter_javascript::language()).unwrap(); &queries.js },
                "ts" => { parser.set_language(&tree_sitter_typescript::language_typescript()).unwrap(); &queries.ts },
                "java" => { parser.set_language(&tree_sitter_java::language()).unwrap(); &queries.java },
                "go" => { parser.set_language(&tree_sitter_go::language()).unwrap(); &queries.go },
                _ => unreachable!(),
            };
            
            if let Some(tree) = parser.parse(&content, None) {
                let matches = cursor.matches(query, tree.root_node(), content.as_bytes());
                for m in matches {
                    for cap in m.captures {
                        if let Ok(mut text) = cap.node.utf8_text(content.as_bytes()) {
                            // Strip quotes safely for imports
                            text = text.trim_matches(|c| c == '"' || c == '\'');
                            imports.push(text.to_string());
                        }
                    }
                }
            }
        } else {
            // Heuristic Fast Fallback Matrix (using the globally compiled lazy regex)
            for caps in HEURISTIC_REGEX.captures_iter(&content) {
                for i in 1..=5 {
                    if let Some(m) = caps.get(i) {
                        imports.push(m.as_str().to_string());
                    }
                }
            }
        }

        // Relative path normalizer explicitly handling physical files
        let mut resolved_imports = Vec::new();
        let parent_dir = path.parent().unwrap_or_else(|| Path::new(""));

        for raw_imp in imports {
            // If the import is relative, map it logically to a known absolute file bound
            if raw_imp.starts_with(".") {
                let clean = clean_heuristic_path(parent_dir, &raw_imp);
                // Attempt to link it to a physical file if it matches known file bounds
                // Often we don't capture the extension in imports (e.g., `import X from "./utils"`)
                let mut matched_path = String::new();
                
                if known_files.contains(&clean) {
                    matched_path = clean;
                } else {
                    for candidate_ext in ["js", "ts", "jsx", "tsx", "py", "rs", "java", "go", "cs", "rb", "php", "cpp", "c", "swift", "kt", "sol"] {
                        let guess = format!("{}.{}", clean, candidate_ext);
                        if known_files.contains(&guess) {
                            matched_path = guess;
                            break;
                        }
                        let index_guess = format!("{}/index.{}", clean, candidate_ext);
                        if known_files.contains(&index_guess) {
                            matched_path = index_guess;
                            break;
                        }
                    }
                }

                if !matched_path.is_empty() {
                    resolved_imports.push(matched_path);
                } else {
                    // Fallback to exactly what AST/regex returned if we can't link it locally
                    resolved_imports.push(raw_imp);
                }
            } else {
                // Absolute library path
                resolved_imports.push(raw_imp);
            }
        }

        Some((path.to_string_lossy().replace("\\", "/").to_string(), resolved_imports))
    }).collect();

    // Map synchronous topological graph resolution
    for (src_path, imports) in parsed_files {
        let source = graph.get_or_insert(&src_path);
        for imp in imports {
            let target = graph.get_or_insert(&imp);
            graph.add_edge_weight(source, target, 1);
        }
    }

    graph
}
