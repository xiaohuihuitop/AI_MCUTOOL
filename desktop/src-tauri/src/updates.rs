use crate::{current_backend, show_error, DesktopState};
use reqwest::blocking::Client;
use semver::Version;
use serde::Deserialize;
use serde_json::json;
use std::{io::Read, os::windows::process::CommandExt, process::Command, sync::atomic::Ordering, thread, time::{Duration, Instant}};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::UpdaterExt;

const LATEST: &str = "https://api.github.com/repos/xiaohuihuitop/AI_MCUTOOL/releases/latest";
const DOWNLOADS: &str = "https://github.com/xiaohuihuitop/AI_MCUTOOL/releases/download";
const MAX_INSTALLER: u64 = 512 * 1024 * 1024; // AI:限制安装包内存占用，单位字节。

#[derive(Deserialize)]
struct Asset { name: String, size: u64 }

#[derive(Deserialize)]
struct Release { tag_name: String, body: Option<String>, draft: bool, prerelease: bool, assets: Vec<Asset> }

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

/// AI:检查最新正式版并处理确认后的更新。@param app 原生桌面。@param manual 是否由用户手动发起。@return 无，后台检查失败写日志。
pub fn check(app: AppHandle, manual: bool) {
    let state = app.state::<DesktopState>();
    if state.checking_update.swap(true, Ordering::SeqCst) {
        if manual { app.dialog().message("正在检查或准备更新。").title("检查更新").show(|_| {}); }
        return;
    }
    thread::spawn(move || {
        let mut interactive = manual;
        let result = check_and_install(&app, &mut interactive);
        let state = app.state::<DesktopState>();
        state.checking_update.store(false, Ordering::SeqCst);
        if let Err(error) = result {
            if interactive { show_error(&app, &error); }
            else { crate::backend::log_error(&state.settings, &error); }
        }
    });
}

/// AI:按固定发布源检查版本，用户确认后查验签名并调用安装器。@param app 桌面实例。@param interactive 是否需要显示结果。@return 完成或原因。
fn check_and_install(app: &AppHandle, interactive: &mut bool) -> Result<(), String> {
    let client = Client::builder().user_agent(concat!("MCUTOOL/", env!("CARGO_PKG_VERSION")))
        .https_only(true).connect_timeout(Duration::from_secs(10)).build().map_err(|_| "无法初始化更新连接")?;
    let metadata = fetch(&client, LATEST, 2 * 1024 * 1024, Duration::from_secs(20))?;
    let release: Release = serde_json::from_slice(&metadata).map_err(|_| "无法读取 GitHub 发布信息")?;
    let current = app.package_info().version.clone();
    let Some(version) = release.newer(&current)? else {
        if *interactive { app.dialog().message(format!("当前版本 {current}，暂无更新。")).title("检查更新").show(|_| {}); }
        return Ok(());
    };
    let name = format!("MCUTOOL-{version}-windows-x64-setup.exe");
    let size = release.asset_size(&name, MAX_INSTALLER)?;
    let signature_size = release.asset_size(&format!("{name}.sig"), 8192)?;
    let notes = release.body.as_deref().unwrap_or("").trim();
    let accepted = app.dialog().message(format!("当前版本 {current}\n最新版本 {version}\n\n{notes}"))
        .title("发现新版本").buttons(MessageDialogButtons::OkCancelCustom("更新并重启".into(), "稍后".into())).blocking_show();
    if !accepted { return Ok(()); }
    *interactive = true;
    let backend = current_backend(app)?;
    let url = format!("{DOWNLOADS}/v{version}/{name}");
    let signature = fetch(&client, &format!("{url}.sig"), signature_size, Duration::from_secs(20))?;
    if signature.len() as u64 != signature_size { return Err("更新签名下载不完整".into()); }
    let updater = app.updater_builder().restart_after_install(true).build().map_err(|_| "无法初始化签名验证")?;
    let update = updater.restore_update(json!({"version":version.to_string(), "url":url, "signature":std::str::from_utf8(&signature).map_err(|_| "签名格式不正确")?.trim()}))
        .map_err(|_| "更新包与本机平台或版本不匹配")?.ok_or("当前版本无需更新")?;
    let bytes = fetch(&client, &url, size, Duration::from_secs(600))?;
    if bytes.len() as u64 != size { return Err("安装包下载不完整，已停止更新".into()); }
    update.verify(&bytes).map_err(|_| "更新包的发布签名或签名版本不正确，已停止安装")?;
    let service = app.path().resource_dir().map_err(|_| "无法确定安装位置")?.join("runtime/MCUTOOL-service/MCUTOOL-service.exe");
    let state = app.state::<DesktopState>();
    if state.exit_pending.swap(true, Ordering::SeqCst) { return Err("正在退出，请稍后再更新".into()); }
    let result = (|| {
        backend.json("POST", "/api/runtime/shutdown").map_err(|e| format!("请稍后更新。{e}"))?;
        // AI:退出确认先于进程释放；同一安装目录的其他后台或 MCP 仍在运行时不能覆盖文件。
        let until = Instant::now() + Duration::from_secs(20);
        loop {
            let status = Command::new(&service).arg("can-uninstall").creation_flags(0x08000000)
                .output().map_err(|_| "无法核对共享运行程序状态")?;
            if status.status.success() { break; }
            if Instant::now() >= until { return Err("仍有程序使用此安装目录，请结束相关会话后重新打开工作台更新".into()); }
            thread::sleep(Duration::from_millis(250));
        }
        update.install(bytes).map_err(|_| "安装器启动失败，请重新打开工作台。".to_owned())
    })();
    state.exit_pending.store(false, Ordering::SeqCst);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    /// AI:验证正式版本的数值比较、相同版本和预发布过滤。@return 无。
    fn only_newer_stable_versions_are_offered() {
        let mut r = Release { tag_name:"v0.10.0".into(), body:None, draft:false, prerelease:false, assets:vec![] };
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
