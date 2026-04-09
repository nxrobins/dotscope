use std::fs::OpenOptions;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicI32, AtomicU32, AtomicU8, Ordering};
use std::io::Write;
use memmap2::{MmapMut, MmapOptions};

#[repr(C, align(4))]
pub struct ControlHeader {
    pub active_buffer: AtomicU8,  // Offset 0: 0 for A, 1 for B
    pub dirty_flag: AtomicU8,     // Offset 1: 0 for Clean, 1 for Dirty (updating)
    _pad: [u8; 2],                // Padding to align to 4 bytes
    pub epoch_version: AtomicU32, // Offset 4: Monotonically increasing epoch
    pub active_readers: AtomicI32,// Offset 8: Reader Epoch count
}

pub struct ControlPlane {
    mmap: MmapMut,
    pub path: PathBuf,
}

impl ControlPlane {
    pub fn new(dotscope_dir: &Path) -> Result<Self, std::io::Error> {
        let control_path = dotscope_dir.join("control.mmap");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&control_path)?;
            
        let metadata = file.metadata()?;
        if metadata.len() < 4096 {
            file.set_len(4096)?;
        }

        let mmap = unsafe { 
            MmapOptions::new().map_mut(&file)? 
        };

        Ok(Self {
            mmap,
            path: control_path,
        })
    }

    pub fn header(&self) -> &ControlHeader {
        unsafe {
            &*(self.mmap.as_ptr() as *const ControlHeader)
        }
    }

    pub fn mark_dirty(&self) {
        self.header().dirty_flag.store(1, Ordering::SeqCst);
    }

    pub fn mark_clean(&self) {
        self.header().dirty_flag.store(0, Ordering::SeqCst);
    }

    pub fn flip_buffer(&self) -> u8 {
        let mut new_active = 0;
        let active = self.header().active_buffer.load(Ordering::SeqCst);
        if active == 0 {
            new_active = 1;
        }
        self.header().active_buffer.store(new_active, Ordering::SeqCst);
        self.header().epoch_version.fetch_add(1, Ordering::SeqCst);
        new_active
    }
}

pub struct TopologyBuffer {
    path: PathBuf,
}

impl TopologyBuffer {
    pub fn new(dotscope_dir: &Path, buffer_id: u8) -> Self {
        let name = if buffer_id == 0 {
            "topology_A.bin"
        } else {
            "topology_B.bin"
        };
        Self {
            path: dotscope_dir.join(name),
        }
    }

    pub fn write_payload(&self, edges_source: &[u8], edges_target: &[u8], edge_weights: &[u8]) -> std::io::Result<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&self.path)?;
            
        file.write_all(edges_source)?;
        file.write_all(edges_target)?;
        file.write_all(edge_weights)?;
        file.sync_all()?;
        Ok(())
    }
}
