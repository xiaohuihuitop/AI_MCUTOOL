use crate::{current_backend, show_main, update_cache::Package, DesktopState};
use reqwest::blocking::Client;
use semver::Version;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{io::Read, os::windows::process::CommandExt, process::Command, sync::atomic::Ordering, thread, time::{Duration, Instant}};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::{Update, UpdaterExt};

const LATEST: &str = "https://api.github.com/repos/xiaohuihuitop/AI_MCUTOOL/releases/latest";
const DOWNLOADS: &str = "https://github.com/xiaohuihuitop/AI_MCUTOOL/releases/download";
const MAX_INSTALLER: u64 = 512 * 1024 * 1024; // AI:限制安装包内存占用，单位字节。

#[derive(Deserialize)]
struct Asset { name: String, size: u64 }

#[derive(Deserialize)]
struct Release { tag_name: String, draft: bool, prerelease: bool, assets: Vec<Asset> }

impl Release {
    /// AI:识别比当前版本新的正式发布。@param current 已安装版本。@return 可更新的版本或无更新。
    fn newer(&self, current: &Version) -> Result<Option<Version>, String> {
        if self.draft || self.prerelease { return Ok(None); }
        let version = self.tag_name.strip_prefix('v').and_then(|v| Version::parse(v).ok())
            .ok_or("正式发布的版本号格式不正确")?;
        Ok((version.pre.is_empty() && version > *current).then_some(version))
    }

    /// AI:确认固定平台文件在同一版本下唯一且大小合理。@param name 所需文件。@param limit 字节上限。@return 发布方记录的文件长度。
    fn asset_size(&self, name: &str, limit: u64) -> Result<u64, String> {
        let mut found = self.assets.iter().filter(|asset| asset.name == name);
        match (found.next(), found.next()) {
            (Some(asset), None) if asset.size > 0 && asset.size <= limit => Ok(asset.size),
            _ => Err(format!("正式版缺少可用的更新文件 {name}")),
        }
    }
}

/// AI:匿名下载固定 HTTPS 内容并限制响应大小。@param client 网络客户端。@param url 官方地址。@param limit 字节上限。@param timeout 请求时限。@return 完整内容或明确错误。
fn fetch(client: &Client, url: &str, limit: u64, timeout: Duration) -> Result<Vec<u8>, String> {
    let response = client.get(url).timeout(timeout).send()
        .map_err(|_| "无法连接 GitHub，请检查网络或代理后再试")?;
    if !response.status().is_success() { return Err(format!("GitHub 返回 HTTP {}", response.status().as_u16())); }
    let mut bytes = Vec::new();
    response.take(limit + 1).read_to_end(&mut bytes).map_err(|_| "下载中断，请稍后重试")?;
    if bytes.len() as u64 > limit { return Err("下载文件超过允许的大小".into()); }
    Ok(bytes)
}

#[derive(Clone, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum Status {
    Idle,
    Checking,
    Current,
    Downloading { version: String, received: u64, total: u64 },
    Ready { version: String },
    Installing { version: String },
    Finishing { message: String },
    Failed { message: String, cached_version: Option<String> },
}

/// AI:发布原生更新进度，网页重载后仍能查询。@param app 桌面；status 本次真实状态。@return 无。
fn report(app: &AppHandle, status: Status) {
    if let Ok(mut value) = app.state::<DesktopState>().update_status.lock() { *value = status; }
}

#[tauri::command]
/// AI:查询当前工具更新进度。@param app 桌面实例。@return 更新阶段或读取错误。
pub fn desktop_update_status(app: AppHandle) -> Result<Status, String> {
    app.state::<DesktopState>().update_status.lock().map(|s| s.clone()).map_err(|_| "无法读取更新状态".into())
}

#[tauri::command]
/// AI:用户手动检查正式工具版。@param app 桌面实例。@return 无，进度通过状态接口公开。
pub fn desktop_prepare_update(app: AppHandle) { check(app, true); }

/// AI:为同平台的正式版本重建设备无关的桌面签名校验器。@param app 桌面；package 待检查的包描述。@return 通过版本策略的更新对象。
fn update_for(app: &AppHandle, package: &Package) -> Result<Update, String> {
    let version = Version::parse(&package.version).map_err(|_| "更新版本无效")?;
    if !version.pre.is_empty() || !version.build.is_empty() || version <= app.package_info().version || package.size == 0 || package.size > MAX_INSTALLER {
        return Err("工具包版本或大小不适用于当前桌面".into());
    }
    let name = format!("MCUTOOL-{version}-windows-x64-setup.exe");
    let updater = app.updater_builder().restart_after_install(true).build().map_err(|_| "无法初始化签名验证")?;
    updater.restore_update(json!({"version":package.version,"url":format!("{DOWNLOADS}/v{version}/{name}"),"signature":package.signature}))
        .map_err(|_| "工具包与本机平台或版本不匹配")?.ok_or("当前工具版本无需更新".into())
}

/// AI:只校验将要使用的同一份字节。@param update 版本签名；package 包描述；bytes 文件。@return 校验结果。
fn verify(update: &Update, package: &Package, bytes: &[u8]) -> Result<(), String> {
    if bytes.len() as u64 != package.size { return Err("工具包长度不符".into()); }
    update.verify(bytes).map_err(|_| "工具包的发布签名或签名版本不正确".into())
}

/// AI:从官方正式版检查并缓存已验签工具包。@param app 原生桌面；replace_bad_cache 允许手动重试时替换已失效的缓存。@return 最终状态或明确错误。
fn prepare(app: &AppHandle, replace_bad_cache: bool) -> Result<Status, String> {
    let client = Client::builder().user_agent(concat!("MCUTOOL/", env!("CARGO_PKG_VERSION")))
        .https_only(true).connect_timeout(Duration::from_secs(10)).build().map_err(|_| "无法初始化更新连接")?;
    let metadata = fetch(&client, LATEST, 2 * 1024 * 1024, Duration::from_secs(20))?;
    let release: Release = serde_json::from_slice(&metadata).map_err(|_| "无法读取 GitHub 发布信息")?;
    let Some(version) = release.newer(&app.package_info().version)? else { return Ok(Status::Current); };
    let name = format!("MCUTOOL-{version}-windows-x64-setup.exe");
    let size = release.asset_size(&name, MAX_INSTALLER)?;
    let sig_size = release.asset_size(&format!("{name}.sig"), 8192)?;
    let url = format!("{DOWNLOADS}/v{version}/{name}");
    let sig = fetch(&client, &format!("{url}.sig"), sig_size, Duration::from_secs(20))?;
    if sig.len() as u64 != sig_size { return Err("工具更新签名下载不完整".into()); }
    let package = Package { version: version.to_string(), size, signature: std::str::from_utf8(&sig).map_err(|_| "工具更新签名无效")?.trim().into() };
    let update = update_for(app, &package)?;
    let dir = cache_dir(app)?;
    if !replace_bad_cache {
        if let Some((cached, bytes)) = Package::load(&dir, MAX_INSTALLER)? {
            if cached.version == package.version && cached.signature == package.signature {
                verify(&update, &package, &bytes)?;
                return Ok(Status::Ready { version: package.version });
            }
        }
    }
    let mut response = client.get(&url).timeout(Duration::from_secs(600)).send()
        .and_then(|r| r.error_for_status()).map_err(|_| "工具包下载失败，请检查网络后重试")?;
    let mut bytes = Vec::new();
    let mut block = [0; 65536];
    report(app, Status::Downloading { version: package.version.clone(), received: 0, total: size });
    loop {
        let count = response.read(&mut block).map_err(|_| "工具包下载中断")?;
        if count == 0 { break; }
        let received = bytes.len() as u64 + count as u64;
        if received > size { return Err("工具包超过发布大小".into()); }
        bytes.extend_from_slice(&block[..count]);
        report(app, Status::Downloading { version: package.version.clone(), received, total: size });
    }
    verify(&update, &package, &bytes)?;
    package.save(&dir, &bytes)?;
    Ok(Status::Ready { version: package.version })
}

/// AI:定位当前用户的桌面更新缓存。@param app 原生应用。@return 工具包缓存目录。
fn cache_dir(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    app.path().app_cache_dir().map(|dir| dir.join("tool-update")).map_err(|_| "无法定位更新缓存".into())
}

/// AI:仅把当前机器可安装且签名有效的本地包提供给离线用户。@param app 原生应用。@return 已验证版本或无。
fn cached_version(app: &AppHandle) -> Option<String> {
    let (package, bytes) = Package::load(&cache_dir(app).ok()?, MAX_INSTALLER).ok()??;
    let update = update_for(app, &package).ok()?;
    verify(&update, &package, &bytes).ok()?;
    Some(package.version)
}

/// AI:启动一次正式版检查，桌面与托盘共用进度。@param app 桌面；manual 是否由用户发起。@return 无。
pub fn check(app: AppHandle, manual: bool) {
    let state = app.state::<DesktopState>();
    if state.settings.test_mode { return; }
    if manual { show_main(&app); }
    if state.checking_update.swap(true, Ordering::SeqCst) { return; }
    // AI:断网或安装占用后已验签的缓存仍可复用；只有缺少可用缓存时才跳过旧文件。
    let replace_bad_cache = manual && matches!(desktop_update_status(app.clone()), Ok(Status::Failed { cached_version: None, .. }));
    report(&app, Status::Checking);
    thread::spawn(move || {
        let status = match prepare(&app, replace_bad_cache) {
            Ok(status) => status,
            Err(message) => {
                crate::backend::log_error(&app.state::<DesktopState>().settings, &message);
                Status::Failed { message, cached_version: cached_version(&app) }
            }
        };
        if manual && matches!(status, Status::Current) { app.dialog().message("当前工具已是最新正式版。").title("检查更新").show(|_| {}); }
        report(&app, status);
        app.state::<DesktopState>().checking_update.store(false, Ordering::SeqCst);
    });
}

#[tauri::command]
/// AI:用户点击安装后重读和复核缓存，再进行后台交接。@param app 原生应用；version 用户看到并选择的工具版本。@return 受理结果或失败原因。
pub async fn desktop_install_update(app: AppHandle, version: String) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    if state.settings.test_mode { return Err("测试模式无法安装正式更新".into()); }
    if state.checking_update.swap(true, Ordering::SeqCst) { return Err("工具更新正在处理中".into()); }
    let worker = app.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let directory = cache_dir(&worker)?;
        let (package, bytes) = Package::load(&directory, MAX_INSTALLER)?.ok_or("尚无已下载的工具包")?;
        if package.version != version { return Err("已准备的版本已变化，请重新检查".into()); }
        let update = update_for(&worker, &package)?;
        verify(&update, &package, &bytes)?;
        report(&worker, Status::Installing { version });
        install(&worker, update, bytes)
    }).await.map_err(|_| "工具更新线程未正常结束".to_owned()).and_then(|r| r);
    if let Err(message) = &result {
        let cached = tauri::async_runtime::spawn_blocking({ let app=app.clone(); move || cached_version(&app) }).await.ok().flatten();
        report(&app, Status::Failed { message:message.clone(), cached_version: cached });
    }
    state.checking_update.store(false, Ordering::SeqCst);
    result
}

/// AI:安装已验签的同一份工具字节。@param app 桌面；update 发布信息；bytes 已验证的包。@return 安装交接结果。
fn install(app: &AppHandle, update: Update, bytes: Vec<u8>) -> Result<(), String> {
    let backend = current_backend(app)?;
    let root = app.path().resource_dir().map_err(|_| "无法确定安装位置")?;
    let service = root.join("runtime/MCUTOOL-service/MCUTOOL-service.exe");
    let state = app.state::<DesktopState>();
    if state.exit_pending.swap(true, Ordering::SeqCst) { return Err("正在退出，请稍后再更新".into()); }
    let mut stopped = false;
    let mut result = (|| {
        let powershell = std::path::PathBuf::from(std::env::var_os("SystemRoot").ok_or("无法定位 Windows")?)
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let processes = |mode: &str| -> Result<bool, String> {
            Command::new(&powershell).args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"])
                .arg(root.join("update-processes.ps1")).arg("-Service").arg(&service)
                .args(["-Mode", mode, "-RuntimePid", &backend.info.pid.to_string()])
                .creation_flags(0x08000000).output().map(|r| r.status.success()).map_err(|e| e.to_string())
        };
        if !processes("Check")? {
            return Err("另一个工具后台仍在使用此安装目录，请结束该后台的工作后再安装。".into());
        }
        let mut confirmation = String::new();
        loop {
            let reply = backend.json("POST", &format!("/api/runtime/shutdown?update=true&confirmation={confirmation}"))?;
            if reply["shutdown_requested"] == true { break; }
            if let Some(key) = reply["confirmation"].as_str() {
                let message = reply["message"].as_str().ok_or("无法读取正在运行的任务")?;
                let accepted = app.dialog().message(message).title("安装更新前有任务正在运行")
                    .buttons(MessageDialogButtons::OkCancelCustom("停止并安装".into(), "继续运行".into())).blocking_show();
                if !accepted {
                    report(app, Status::Ready { version:update.version.clone() });
                    return Ok(());
                }
                confirmation = key.to_owned();
            } else if reply["waiting_firmware"] == true {
                report(app, Status::Finishing { message:"等待工具板写入、重连并回读版本…".into() });
                loop {
                    thread::sleep(Duration::from_millis(500));
                    let status = backend.json("GET", "/api/runtime/status")?;
                    match status["firmware_update"]["phase"].as_str() {
                        Some("succeeded") => break,
                        Some("installing" | "reconnecting") => continue,
                        _ => return Err("工具板固件回读未确认，请核对结果后再安装桌面更新。".into()),
                    }
                }
            } else if reply["waiting_actions"] == true {
                report(app, Status::Finishing { message:"等待板上动作收尾…".into() });
                thread::sleep(Duration::from_millis(400));
            } else {
                return Err("后台未确认升级收尾状态。".into());
            }
        }
        stopped = true;
        // AI:退出确认先于进程释放；同一安装目录的其他后台或 MCP 仍在运行时不能覆盖文件。
        let until = Instant::now() + Duration::from_secs(20);
        loop {
            if processes("CloseBridges")? { break; }
            if Instant::now() >= until { return Err("仍有程序使用此安装目录，请结束相关会话后重新打开工作台更新".into()); }
            thread::sleep(Duration::from_millis(250));
        }
        report(app, Status::Installing { version:update.version.clone() });
        update.install(bytes).map_err(|e| format!("启动更新安装器失败：{e}"))
    })();
    if let (true, Err(cause)) = (stopped, &result) {
        // AI:安装交接失败后恢复原版后台和页面会话；恢复失败时仍保留仅退出桌面端的路径。
        let recovery = (|| -> Result<(), String> {
            let restored = crate::backend::Backend::start(&service, &state.settings)?;
            let url = restored.info.url.parse().map_err(|_| "后台地址无效")?;
            *state.backend.lock().map_err(|_| "桌面会话不可用")? = Some(restored);
            *state.error.lock().map_err(|_| "桌面状态不可用")? = None;
            app.get_webview_window("main").ok_or("工作台窗口不可用")?
                .navigate(url).map_err(|_| "工作台页面无法打开".to_owned())
        })();
        result = Err(match recovery {
            Ok(()) => format!("{cause}。原版本后台和桌面会话已恢复，可在连接设置中重新选择设备。"),
            Err(reason) => format!("{cause}。恢复工作台失败：{reason}。请从托盘选择仅退出桌面端，再打开工作台。"),
        });
    }
    state.exit_pending.store(false, Ordering::SeqCst);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    /// AI:验证正式版本的数值比较、相同版本和预发布过滤。@return 无。
    fn only_newer_stable_versions_are_offered() {
        let mut r = Release { tag_name:"v0.10.0".into(), draft:false, prerelease:false, assets:vec![] };
        let current = Version::parse("0.9.9").unwrap();
        assert_eq!(r.newer(&current).unwrap().unwrap(), Version::parse("0.10.0").unwrap());
        for tag in ["v0.9.9", "v0.5.0", "v1.0.0-rc.1"] {
            r.tag_name = tag.into();
            assert!(r.newer(&current).unwrap().is_none());
        }
        r.tag_name = "v1.0.0".into();
        r.prerelease = true;
        assert!(r.newer(&current).unwrap().is_none());
    }

    #[test]
    #[ignore = "需显式指定已下载的正式安装器和同名签名目录"]
    /// AI:使用当前客户端发布公钥核验正式安装器。@return 无，签名不匹配或文件缺失时断言失败。
    fn published_installer_matches_embedded_key() {
        let config: serde_json::Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let version = config["version"].as_str().unwrap();
        let name = format!("MCUTOOL-{version}-windows-x64-setup.exe");
        let dir = std::path::PathBuf::from(std::env::var_os("MCUTOOL_VERIFY_DIRECTORY").unwrap());
        let bytes = std::fs::read(dir.join(&name)).unwrap();
        let signature = std::fs::read_to_string(dir.join(format!("{name}.sig"))).unwrap();
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context.config_mut().plugins.0.insert("updater".into(), config["plugins"]["updater"].clone());
        let app = tauri::test::mock_builder().plugin(tauri_plugin_updater::Builder::new().build()).build(context).unwrap();
        let updater = app.updater_builder().version_comparator(|_, _| true).build().unwrap();
        let release = json!({"version":version,"url":format!("{DOWNLOADS}/v{version}/{name}"),"signature":signature.trim()});
        updater.restore_update(release).unwrap().unwrap().verify(&bytes).unwrap();
    }

    #[test]
    /// AI:使用 Tauri CLI 签名的固定样本检验内容及版本绑定。@return 无，未执行安装器。
    fn signature_binds_both_package_and_version() {
        let key = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDU0Q0Y0RDRFMkFGNzVFRjgKUldUNFh2Y3FUazNQVk5YRlJMbk5nNk4ybTczYnRzYkxKaUZPNTBsRmV2MjNGVms5RitKb1psS04K";
        let signature = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVUNFh2Y3FUazNQVkNHc1dOTDVPRFZzbk5VWlgwNTdXNWt2YUE4eldNTVNDUUErbHNWbkxtYkJkTW93R1ZiRjZ5Nmg5Si9EZHlJZG4zZzluWVpnQ2h5ZVgyRWEyUzZCQUFFPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzk1MDA4NDA2CWZpbGU6Zml4dHVyZS5iaW4JdmVyc2lvbjo5LjAuMApEMDdBbHRiS3RNVXMzVEI2eDE2T0V6YnlrbkhqKzRueEV5ZkZKeWRHSTZYU01WRGlUT3lqYjVFUmVVVzI2N3F4RlI1VGt2djNWenFQcDBDQ1RZR1RDdz09Cg==";
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context.config_mut().plugins.0.insert("updater".into(), json!({"pubkey":key,"requireSignedVersion":true}));
        let app = tauri::test::mock_builder().plugin(tauri_plugin_updater::Builder::new().build())
            .build(context).unwrap();
        let updater = app.updater_builder().pubkey(key).endpoints(vec![LATEST.parse().unwrap()]).unwrap().build().unwrap();
        let for_version = |v: &str| updater.restore_update(json!({"version":v,"url":"https://example.invalid/test.exe","signature":signature})).unwrap().unwrap();
        let bytes = b"MCU TOOL update verification\n";
        assert!(for_version("9.0.0").verify(bytes).is_ok());
        assert!(for_version("9.0.0").verify(b"modified").is_err());
        assert!(for_version("9.0.1").verify(bytes).is_err());
    }
}
