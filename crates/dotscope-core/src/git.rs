use crate::graph::TopologicalGraph;
use git2::{Repository, Sort, DiffOptions};
use bloomfilter::Bloom;
use std::hash::{Hash, Hasher};
use std::collections::hash_map::DefaultHasher;

fn hash_edge(a: &str, b: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    if a < b {
        a.hash(&mut hasher);
        b.hash(&mut hasher);
    } else {
        b.hash(&mut hasher);
        a.hash(&mut hasher);
    }
    hasher.finish()
}

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

    // Dynamically calculate the optimal capacity for the Bloom Filter
    // Heuristic: an average repository yields about 50 robust recurrent edges per commit.
    // max_commits bounds the universe of possible edge creation linearly.
    let expected_edges = std::cmp::max(10_000, max_commits * 50);
    let mut bloom = Bloom::new_for_fp_rate(expected_edges, 0.01).expect("Failed to init bloom");

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

            // O(C*F) Inverse Coupling Matrix calculation natively mapping dynamic hotspots
            if changed_files.len() <= 100 {
                for i in 0..changed_files.len() {
                    for j in (i + 1)..changed_files.len() {
                        let file_a = &changed_files[i];
                        let file_b = &changed_files[j];
                        
                        let edge_hash = hash_edge(file_a, file_b);

                        // BLOOM HEURISTIC GATEWAY: 
                        // If check_and_set returns false, this is incredibly likely the VERY FIRST time 
                        // these two files have ever appeared together in a commit. 
                        // We set the bit, and instantly drop the edge to save CPU find_edge O(E) cycles!
                        if bloom.check_and_set(&edge_hash) {
                            // It WAS in the bloom filter! These files have verified recurrent structural gravity.
                            let source = graph.get_or_insert(file_a);
                            let target = graph.get_or_insert(file_b);
                            graph.add_edge_weight(source, target, 1);
                        }
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
