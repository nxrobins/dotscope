use ignore::overrides::OverrideBuilder;
use ignore::WalkBuilder;
use pyo3::prelude::*;

#[pyfunction]
pub fn walk_repository(root: &str) -> PyResult<Vec<String>> {
    let mut overrides = OverrideBuilder::new(root);
    
    // Explicitly prune absolute dark-matter topologies mathematically
    let prune_rules = [
        "!**/.git/**",
        "!**/node_modules/**",
        "!**/vendor/**",
        "!**/target/**",
        "!**/dist/**",
        "!**/build/**",
        "!**/__pycache__/**",
        "!**/.idea/**",
        "!**/.vscode/**",
        "!**/*.pyc",
    ];
    
    for rule in prune_rules {
        let _ = overrides.add(rule);
    }
    
    let override_set = overrides.build().expect("Failed to build static override set");

    let mut builder = WalkBuilder::new(root);
    builder
        .hidden(false) 
        .git_ignore(true)
        .overrides(override_set);

    let walker = builder.build();
    let mut files = Vec::new();

    for result in walker {
        if let Ok(entry) = result {
            if entry.file_type().map(|f| f.is_file()).unwrap_or(false) {
                if let Some(path_str) = entry.path().to_str() {
                    files.push(path_str.to_string());
                }
            }
        }
    }

    Ok(files)
}
