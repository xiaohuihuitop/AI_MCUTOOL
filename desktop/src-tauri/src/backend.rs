use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{fs, io::Write, path::{Path, PathBuf}, process::{Command, Stdio}, thread, time::{Duration, Instant}};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub data_dir: PathBuf,
    pub port: u16,
    #[serde(skip)]
    pub test_mode: bool,
    #[serde(skip)]
    pub hidden: bool,
}

impl Settings {
    /// AI:读取明确的桌面配置并应用命令行覆盖。@param args 启动参数。@return 配置或可显示的输入错误，不寻找其他数据目录。
    pub fn load(args: &[String]) -> Result<Self, String> {
        let local = std::env::var_os("LOCALAPPDATA").ok_or("无法定位当前Windows用户目录")?;
        let root = PathBuf::from(local).join("MCU_TOOL");
        let file = root.join("desktop.json");
        let mut settings = if file.exists() {
            serde_json::from_slice::<Self>(&fs::read(&file).map_err(|_| "无法读取桌面配置")?)
                .map_err(|_| "桌面配置格式不正确，请检查用户目录中的MCU_TOOL/desktop.json")?
        } else {
            Self { data_dir: root.join("data"), port: 5210, test_mode: false, hidden: false }
        };
        settings.apply_args(args)?;
        if !settings.data_dir.is_absolute() || settings.port < 1024 {
            return Err("数据目录必须为绝对路径，端口须为1024到65535".into());
        }
        Ok(settings)
    }

    /// AI:应用显式启动选项。@param args 不含程序路径的参数。@return 无或参数错误。
    fn apply_args(&mut self, args: &[String]) -> Result<(), String> {
        let mut items = args.iter();
        while let Some(argument) = items.next() {
            match argument.as_str() {
                "--data-dir" => self.data_dir = PathBuf::from(items.next().ok_or("缺少数据目录")?),
                "--port" => self.port = items.next().ok_or("缺少端口")?.parse().map_err(|_| "端口不合法")?,
                "--test-mode" => self.test_mode = true,
                "--hidden" => self.hidden = true,
                _ => return Err(format!("不支持的启动参数：{}", argument)),
            }
        }
        Ok(())
    }
}

#[derive(Clone, Deserialize)]
pub struct Bootstrap {
    pub url: String,
    pub token: String,
    pub instance_id: String,
    pub session_id: String,
    pub client_id: String,
    pub data_dir: PathBuf,
    pub version: String,
    pub test_mode: bool,
}

#[derive(Clone)]
pub struct Backend {
    pub info: Bootstrap,
    client: Client,
}

impl Backend {
    /// AI:通过随附可执行程序启动同一后台并取得私有会话。@param service 随附程序；settings 显式配置。@return 已核验后台或错误；不连接硬件。
    pub fn start(service: &Path, settings: &Settings) -> Result<Self, String> {
        if !service.is_file() {
            return Err("随附运行程序缺失，请重新安装MCU TOOL。原记录不会被删除。".into());
        }
        fs::create_dir_all(&settings.data_dir).map_err(|_| "无法创建或访问记录目录")?;
        let mut command = Command::new(service);
        command.args(["desktop-start", "--data-dir"]).arg(&settings.data_dir)
            .args(["--port", &settings.port.to_string()])
            .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
        if settings.test_mode { command.arg("--test-mode"); }
        #[cfg(windows)]
        command.creation_flags(0x08000000); // AI:隐藏辅助进程控制台，MCP仍可使用标准输入输出。
        let mut process = command.spawn().map_err(|error| format!("运行程序无法启动：{error}"))?;
        let deadline = Instant::now() + Duration::from_secs(50);
        loop {
            if process.try_wait().map_err(|_| "无法查询启动进程")?.is_some() { break; }
            if Instant::now() >= deadline {
                let _ = process.kill();
                let _ = process.wait();
                return Err("后台未在规定时间内就绪，请查看记录目录中的runtime.log后重新打开。".into());
            }
            thread::sleep(Duration::from_millis(100));
        }
        let output = process.wait_with_output().map_err(|_| "读取启动结果失败")?;
        if !output.status.success() {
            // AI:只展示结构化错误说明；私有管道可能含凭据，禁止原样输出或写日志。
            let error = service_error(&output.stderr);
            return Err(error.as_ref().and_then(|v| v.pointer("/error/message")).and_then(Value::as_str)
                .unwrap_or("后台启动失败，请查看记录目录中的runtime.log。其他客户端仍在线时需先正常退出旧后台。")
                .to_owned());
        }
        let info: Bootstrap = serde_json::from_slice(&output.stdout).map_err(|_| "启动结果不符合桌面协议")?;
        if info.url != format!("http://127.0.0.1:{}", settings.port) || info.version != env!("CARGO_PKG_VERSION") || info.test_mode != settings.test_mode {
            return Err("后台地址、版本或运行模式与桌面配置不一致".into());
        }
        let backend = Self { info, client: Client::builder().no_proxy().timeout(Duration::from_secs(12)).build().map_err(|_| "无法创建本机连接")? };
        let ping = backend.json("GET", "/api/ping")?;
        if ping["instance_id"].as_str() != Some(backend.info.instance_id.as_str()) || ping["desktop_protocol"] != 1 {
            return Err("后台实例已变化，请重新打开桌面端".into());
        }
        Ok(backend)
    }

    /// AI:向既定本机后台发送一次会话请求。@param method HTTP方法；path 固定接口。@return JSON结果，不自动重试。
    pub fn json(&self, method: &str, path: &str) -> Result<Value, String> {
        let response = self.client.request(method.parse().map_err(|_| "内部请求方法不合法")?, format!("{}{}", self.info.url, path))
            .bearer_auth(&self.info.token).header("X-Session-ID", &self.info.session_id)
            .send().map_err(|_| "共享后台无法访问，请重新打开桌面端；设备输出未改变")?;
        let status = response.status();
        let body: Value = response.json().map_err(|_| "后台响应格式不正确")?;
        if !status.is_success() {
            return Err(body.pointer("/error/message").and_then(Value::as_str).unwrap_or("后台拒绝本次请求").to_owned());
        }
        Ok(body)
    }

    /// AI:提供页面使用的桌面会话身份。@return 页面所需信息，不包含后台访问令牌。
    pub fn context(&self) -> Value {
        json!({"client_id":self.info.client_id,"session_id":self.info.session_id,"instance_id":self.info.instance_id,
               "data_dir":self.info.data_dir,"version":self.info.version})
    }

    /// AI:把已授权的下载写入用户选定文件。@param path 既定后台相对接口；target 保存目标。@return 完成或明确错误；失败保留原目标。
    pub fn save(&self, path: &str, target: &Path) -> Result<(), String> {
        let parent = target.parent().ok_or("保存位置不合法")?;
        let mut response = self.client.get(format!("{}{}", self.info.url, path)).timeout(Duration::from_secs(120))
            .bearer_auth(&self.info.token).header("X-Session-ID", &self.info.session_id)
            .send().map_err(|_| "下载请求失败")?;
        if !response.status().is_success() { return Err("后台拒绝导出，请确认文件存在且会话仍然有效".into()); }
        let mut file = tempfile::NamedTempFile::new_in(parent).map_err(|_| "保存目录不可写")?;
        response.copy_to(file.as_file_mut()).map_err(|_| "下载未完整完成，原目标文件保持")?;
        file.as_file_mut().flush().map_err(|_| "下载文件写入失败")?;
        file.as_file().sync_all().map_err(|_| "下载文件保存失败")?;
        file.persist(target).map_err(|_| "无法保存到所选位置，请检查文件占用或权限")?;
        Ok(())
    }
}

/// AI:从服务标准错误中读取最后一条结构化错误，忽略库启动警告。@param bytes 标准错误。@return 错误对象或空。
pub fn service_error(bytes: &[u8]) -> Option<Value> {
    String::from_utf8_lossy(bytes).lines().rev().filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|value| value.pointer("/error/message").and_then(Value::as_str).is_some())
}

/// AI:记录不含凭据的桌面错误。@param settings 数据位置；message 已筛选的说明。@return 无，写入失败不会改动设备。
pub fn log_error(settings: &Settings, message: &str) {
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(settings.data_dir.join("desktop.log")) {
        let _ = writeln!(file, "{} {}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|x|x.as_secs()).unwrap_or(0), message);
    }
}

/// AI:构造记录导出路径。@param record 记录标识；file 真实文件名。@return 编码后的同源路径，拒绝路径穿越。
pub fn recording_path(record: &str, file: &str) -> Result<String, String> {
    if [record, file].iter().any(|value| value.is_empty() || *value == "." || *value == ".." || value.contains(['/', '\\', '\0'])) {
        return Err("记录文件名不合法".into());
    }
    let mut url = reqwest::Url::parse("http://127.0.0.1").map_err(|_| "内部地址不合法")?;
    url.path_segments_mut().map_err(|_| "内部地址不合法")?.extend(["api", "recordings", record, file]);
    Ok(url.path().to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    /// AI:验证记录路径只允许一个目录与一个文件。@return 无，失败触发断言。
    fn record_download_never_changes_the_selected_directory() {
        assert!(recording_path("../secrets", "runtime.json").is_err());
        assert!(recording_path("session", "..\\runtime.json").is_err());
        assert!(recording_path("session", "串口.bin").unwrap().starts_with("/api/recordings/session/"));
    }

    #[test]
    /// AI:验证明确启动参数不引入猜测和自动选项。@return 无，失败触发断言。
    fn launch_arguments_are_explicit_and_do_not_switch_to_another_port() {
        let mut settings = Settings { data_dir: PathBuf::from("C:/records"), port:5210, test_mode:false, hidden:false };
        settings.apply_args(&["--port".into(), "28768".into(), "--hidden".into()]).unwrap();
        assert_eq!(settings.port, 28768);
        assert!(settings.hidden);
        assert!(settings.apply_args(&["--port".into(), "bad".into()]).is_err());
        assert!(settings.apply_args(&["--automatic-reconnect".into()]).is_err());
    }
}
