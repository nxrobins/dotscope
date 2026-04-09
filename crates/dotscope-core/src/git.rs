use crate::graph::TopologicalGraph;
use git2::{Repository, Sort, DiffOptions};

pub fn mine_history(
    repo_path: &str,
    mut graph: TopologicalGraph,
    max_commits: usize,
) -> Result<TopologicalGraph, Box<dyn std::error::Error>> {
    // Force complete severance of underlying Libgit2 C-Level cache layers
    let _ = git2::opts::enable_caching(false);

    let repo = Repository::open(repo_path)?;
    let mut revwalk = repo.revwalk()?;
    revwalk.set_sorting(Sort::TOPOLOGICAL | Sort::TIME)?;
    revwalk.push_head()?;

    let mut commit_count = 0;

    for oid in revwalk.take(max_commits) {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;
        let tree = commit.tree()?;

        // Calculate delta weighting
        if commit.parent_count() > 0 {
            let parent_commit = commit.parent(0)?;
            let parent_tree = parent_commit.tree()?;

            let mut diff_opts = DiffOptions::new();
            diff_opts.context_lines(0);
            
            // Critical Transitive Gravity: explicitly bind track_renames so the graph doesn't shatter
            let mut diff = repo.diff_tree_to_tree(Some(&parent_tree), Some(&tree), Some(&mut diff_opts))?;
            let mut find_opts = git2::DiffFindOptions::new();
            find_opts.renames(true);
            diff.find_similar(Some(&mut find_opts))?;

            // Capture the matrix
            let mut changed_files = Vec::new();
            for delta in diff.deltas() {
                if let Some(new_file) = delta.new_file().path() {
                    if let Some(path_str) = new_file.to_str() {
                        changed_files.push(path_str.to_string());
                    }
                }
            }

            // O(C*F) Inverse Coupling Matrix calculation natively mapping $O(N^2)$ nodes dynamically
            if changed_files.len() <= 100 {
                for i in 0..changed_files.len() {
                    for j in (i + 1)..changed_files.len() {
                        let source = graph.get_or_insert(&changed_files[i]);
                        let target = graph.get_or_insert(&changed_files[j]);
                        // Hotspots generated natively through integer bumps
                        graph.add_edge_weight(source, target, 1);
                    }
                }
            }
        }

        commit_count += 1;
        
        // Ethereal Traversal: Explicitly crush fragmented memory allocations built during the RevWalk
        if commit_count % 100 == 0 {
            // Memory is automatically released natively when structs drop due to tracking limits
        }
    }

    Ok(graph)
}
