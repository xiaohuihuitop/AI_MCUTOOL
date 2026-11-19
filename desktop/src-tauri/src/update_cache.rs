use serde::{Deserialize, Serialize};
use std::{fs::{self, File}, io::{Read, Write}, path::Path};
use tempfile::NamedTempFile;

#[derive(Clone, Serialize, Deserialize)]
pub struct Package {
    pub version: String,
    pub size: u64,
    pub signature: String,
}

// AI:只允许本应用的小型版本与签名描述，后方紧跟原始安装器。
const HEADER_LIMIT: usize = 16 * 1024;

impl Package {
    /// AI:将已验签的包和描述一起原子保存。@param directory 更新目录；bytes 安装文件。@return 持久化结果。
    pub fn save(&self, directory: &Path, bytes: &[u8]) -> Result<(), String> {
        let header = serde_json::to_vec(self).map_err(|_| "无法保存版本信息")?;
        if header.len() > HEADER_LIMIT || bytes.len() as u64 != self.size { return Err("工具包信息不一致".into()); }
        fs::create_dir_all(directory).map_err(|_| "无法创建更新目录")?;
        let mut temp = NamedTempFile::new_in(directory).map_err(|_| "无法创建下载文件")?;
        temp.write_all(&(header.len() as u32).to_le_bytes()).and_then(|_| temp.write_all(&header))
            .and_then(|_| temp.write_all(bytes)).and_then(|_| temp.as_file().sync_all()).map_err(|_| "无法保存工具包")?;
        temp.persist(directory.join("tool.package")).map_err(|_| "无法替换工具包")?;
        Ok(())
    }

    /// AI:从同一文件句柄读取描述和内容，校验前先限制长度。@param directory 更新目录；limit 安装器上限。@return 缓存包或无缓存。
    pub fn load(directory: &Path, limit: u64) -> Result<Option<(Self, Vec<u8>)>, String> {
        let mut file = match File::open(directory.join("tool.package")) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("无法打开工具包缓存".into()),
        };
        let mut length = [0u8; 4];
        file.read_exact(&mut length).map_err(|_| "工具包缓存描述不完整")?;
        let length = u32::from_le_bytes(length) as usize;
        if length > HEADER_LIMIT { return Err("工具包缓存描述过大".into()); }
        let mut header = vec![0u8; length];
        file.read_exact(&mut header).map_err(|_| "工具包缓存描述不完整")?;
        let package: Self = serde_json::from_slice(&header).map_err(|_| "工具包缓存描述无效")?;
        if package.size == 0 || package.size > limit { return Err("工具包缓存大小无效".into()); }
        let size = file.metadata().map_err(|_| "无法读取工具包大小")?.len();
        if size != 4 + length as u64 + package.size { return Err("工具包缓存长度不符".into()); }
        let mut bytes = Vec::new();
        file.take(package.size + 1).read_to_end(&mut bytes).map_err(|_| "工具包缓存读取失败")?;
        if bytes.len() as u64 != package.size { return Err("工具包缓存不完整".into()); }
        Ok(Some((package, bytes)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    /// AI:缓存替换失败后旧包保持完整，截断或超限的内容不能交付安装。@return 无。
    fn cache_is_atomic_and_bounded() {
        let dir = tempfile::tempdir().unwrap();
        let p = Package { version: "1.2.3".into(), size: 3, signature: "test".into() };
        p.save(dir.path(), b"abc").unwrap();
        assert!(p.save(dir.path(), b"a").is_err());
        assert_eq!(Package::load(dir.path(), 3).unwrap().unwrap().1, b"abc");
        assert!(Package::load(dir.path(), 2).is_err());
        fs::write(dir.path().join("tool.package"), [255u8; 4]).unwrap();
        assert!(Package::load(dir.path(), 3).is_err());
    }
}
