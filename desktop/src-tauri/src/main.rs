#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod updates;
use backend::{Backend, Settings};
use serde_json::{json, Value};
use std::{io::Write, path::PathBuf, sync::{atomic::{AtomicBool, Ordering}, Mutex}, thread, time::Duration};
use tauri::{menu::{Menu, MenuItem}, tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent}, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

struct DesktopState {
    backend: Mutex<Option<Backend>>,
    error: Mutex<Option<String>>,
    // AI:请求门闩与最终退出分开，后台拒绝退出时不能停止原生续约。
    exit_pending: AtomicBool,
    checking_update: AtomicBool,
    exiting: AtomicBool,
    settings: Settings,
}

/// AI:取得当前有效桌面会话。@param app 桌面实例。@return 会话或错误，不重新登记或重启后台。
fn current_backend(app: &AppHandle) -> Result<Backend, String> {
    let state = app.state::<DesktopState>();
    if let Some(error) = state.error.lock().map_err(|_| "桌面状态不可用")?.as_ref() { return Err(error.clone()); }
    let backend = state.backend.lock().map_err(|_| "桌面状态不可用")?.clone();
    backend.ok_or_else(|| "后台尚未准备完成".into())
}

/// AI:显示已有工作台窗口。@param app 桌面实例。@return 无，不创建新后台。
fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// AI:向用户显示明确错误。@param app 桌面实例；message 错误说明。@return 无。
fn show_error(app: &AppHandle, message: &str) {
    backend::log_error(&app.state::<DesktopState>().settings, message);
    show_main(app);
    app.dialog().message(message).title("MCU TOOL").kind(MessageDialogKind::Error).show(|_| {});
}

/// AI:明确退出桌面会话或整个后台。@param app 桌面实例；stop 是否请求停止共享后台。@return 完成或被后台条件拒绝。
fn exit_desktop(app: &AppHandle, stop: bool) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    if state.exit_pending.swap(true, Ordering::SeqCst) { return Err("退出正在处理中".into()); }
    let backend = state.backend.lock().map_err(|_| "桌面状态不可用")?.clone();
    if stop {
        let result = backend.as_ref().ok_or_else(|| "后台状态未确认；可选择仅退出桌面端".to_owned())
            .and_then(|backend| backend.json("POST", "/api/runtime/shutdown"));
        if let Err(error) = result {
            state.exit_pending.store(false, Ordering::SeqCst);
            return Err(error);
        }
    } else if let Some(backend) = backend {
        if let Err(error) = backend.json("DELETE", "/api/sessions/current") {
            // AI:用户明确只退出桌面端；未确认分离时记录错误，不声称后台或设备已停止。
            backend::log_error(&state.settings, &format!("桌面会话分离未确认：{error}"));
        }
    }
    state.exiting.store(true, Ordering::SeqCst);
    app.exit(0);
    Ok(())
}

/// AI:弹出保存对话框并下载指定内容。@param app 桌面实例；path 已校验后台接口；name 默认文件名。@return true已保存、false用户取消。
fn save_dialog(app: &AppHandle, path: &str, name: &str) -> Result<bool, String> {
    let backend = current_backend(app)?;
    let target = app.dialog().file().set_file_name(name).blocking_save_file();
    let Some(target) = target else { return Ok(false); };
    let target: PathBuf = target.into_path().map_err(|_| "所选保存位置不受支持")?;
    backend.save(path, &target)?;
    Ok(true)
}

#[tauri::command]
/// AI:返回原生进程持续维护的桌面会话。@param app 桌面实例。@return 页面初始化身份或错误。
fn desktop_context(app: AppHandle) -> Result<Value, String> { Ok(current_backend(&app)?.context()) }

#[tauri::command]
/// AI:读取启动错误。@param app 桌面实例。@return 不含凭据的启动状态。
fn desktop_start_status(app: AppHandle) -> Value {
    let state = app.state::<DesktopState>();
    json!({"error": state.error.lock().ok().and_then(|x|x.clone())})
}

#[tauri::command]
/// AI:明确只退出桌面会话。@param app 桌面实例。@return 请求执行结果。
async fn desktop_exit(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || exit_desktop(&app, false)).await.map_err(|_| "退出处理失败")?
}

#[tauri::command]
/// AI:经过共享退出检查后停止后台并退出。@param app 桌面实例。@return 结果或仍有使用者等拒绝原因。
async fn desktop_stop(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || exit_desktop(&app, true)).await.map_err(|_| "退出处理失败")?
}

#[tauri::command]
/// AI:导出脱敏诊断ZIP。@param app 桌面实例。@return 是否保存，失败返回错误。
async fn desktop_export(app: AppHandle) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || save_dialog(&app, "/api/diagnostics", "MCUTOOL-诊断日志.zip")).await.map_err(|_| "导出处理失败")?
}

#[tauri::command]
/// AI:保存用户选定的原始记录文件。@param app 桌面实例；record 记录目录；filename 文件名。@return 是否保存或错误。
async fn desktop_save_recording(app: AppHandle, record: String, filename: String) -> Result<bool, String> {
    let path = backend::recording_path(&record, &filename)?;
    tauri::async_runtime::spawn_blocking(move || save_dialog(&app, &path, &filename)).await.map_err(|_| "文件保存失败")?
}

#[tauri::command]
/// AI:保存当前图表的CSV快照。@param app 桌面实例；filename 默认名称；content UTF-8文本。@return true已保存、false已取消，失败保留原文件。
async fn desktop_save_waveform(app: AppHandle, filename: String, content: String) -> Result<bool, String> {
    if !filename.starts_with("MCUTOOL-") || !filename.ends_with(".csv") || filename.contains(['/', '\\', '\0']) || content.len() > 128 * 1024 * 1024 {
        return Err("波形导出内容或名称不合法".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let target = app.dialog().file().add_filter("CSV 波形数据", &["csv"]).set_file_name(&filename).blocking_save_file();
        let Some(target) = target else { return Ok(false); };
        let target: PathBuf = target.into_path().map_err(|_| "所选保存位置不受支持")?;
        let parent = target.parent().ok_or("保存位置不合法")?;
        let mut file = tempfile::NamedTempFile::new_in(parent).map_err(|_| "保存目录不可写")?;
        file.write_all(content.as_bytes()).map_err(|_| "波形数据写入失败，原文件保持")?;
        file.flush().map_err(|_| "波形数据写入失败")?;
        file.as_file().sync_all().map_err(|_| "波形数据保存失败")?;
        file.persist(target).map_err(|_| "无法保存到所选位置，请检查文件占用或权限")?;
        Ok(true)
    }).await.map_err(|_| "波形导出失败")?
}

/// AI:原生线程维护会话，隐藏窗口不会暂停续约。@param app 桌面实例；backend 已验证后台。@return 无；错误后停止续约并提示，不自动恢复。
fn keepalive(app: AppHandle, backend: Backend) {
    thread::spawn(move || loop {
        for _ in 0..15 {
            thread::sleep(Duration::from_secs(1));
            if app.state::<DesktopState>().exiting.load(Ordering::SeqCst) { return; }
        }
        if let Err(error) = backend.json("POST", "/api/sessions/heartbeat") {
            let state = app.state::<DesktopState>();
            if state.exiting.load(Ordering::SeqCst) { return; }
            let message = format!("{error}。请从托盘退出桌面端后重新打开；已接受的板上动作不受此窗口影响。");
            backend::log_error(&state.settings, &message);
            if let Ok(mut status) = state.error.lock() { *status = Some(message); }
            if let Some(tray) = app.tray_by_id("main") { let _ = tray.set_tooltip(Some("MCU TOOL · 后台连接中断")); }
            return;
        }
    });
}

/// AI:启动Windows工作台。无参数，读取进程参数；返回值由桌面事件循环管理。
fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments == ["--version"] { println!("{}", env!("CARGO_PKG_VERSION")); return; }
    let parsed = Settings::load(&arguments);
    let config_error = parsed.as_ref().err().cloned();
    // AI:无效配置仅展示错误页，不据此启动另一数据目录或后台。
    let settings = parsed.unwrap_or(Settings { data_dir: PathBuf::new(), port: 5210, test_mode: false, hidden: false });
    let allowed_port = settings.port;
    let hidden = settings.hidden;
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            let state = app.state::<DesktopState>();
            match Settings::load(&args.into_iter().skip(1).collect::<Vec<_>>()) {
                Ok(request) if request.data_dir == state.settings.data_dir && request.port == state.settings.port && request.test_mode == state.settings.test_mode => show_main(app),
                _ => show_error(app, "工作台已打开。若要改用其他记录目录，请先明确退出当前桌面端。"),
            }
        }))
        .manage(DesktopState { backend: Mutex::new(None), error: Mutex::new(config_error.clone()), exit_pending: AtomicBool::new(false), checking_update: AtomicBool::new(false), exiting: AtomicBool::new(false), settings })
        .invoke_handler(tauri::generate_handler![desktop_context, desktop_start_status, desktop_exit, desktop_stop, desktop_export, desktop_save_recording, desktop_save_waveform])
        .setup(move |app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("MCU TOOL · 设备工作台").inner_size(1280.0, 900.0).min_inner_size(920.0, 680.0)
                .visible(!hidden).center()
                .on_navigation(move |url| url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost") ||
                    (url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == Some(allowed_port)))
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                .build()?;
            let handle = app.handle().clone();
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    if !handle.state::<DesktopState>().exiting.load(Ordering::SeqCst) {
                        api.prevent_close();
                        if let Some(window) = handle.get_webview_window("main") { let _ = window.hide(); }
                    }
                }
            });
            let show = MenuItem::with_id(app, "show", "显示工作台", true, None::<&str>)?;
            let update = MenuItem::with_id(app, "update", "检查更新…", true, None::<&str>)?;
            let export = MenuItem::with_id(app, "export", "导出诊断日志…", true, None::<&str>)?;
            let exit = MenuItem::with_id(app, "exit", "退出桌面端（后台继续运行）", true, None::<&str>)?;
            let stop = MenuItem::with_id(app, "stop", "停止后台并退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &update, &export, &exit, &stop])?;
            let tray = TrayIconBuilder::with_id("main").icon(app.default_window_icon().ok_or("缺少应用图标")?.clone())
                .tooltip("MCU TOOL · 关闭窗口后继续运行").menu(&menu).show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event { show_main(tray.app_handle()); }
                })
                .on_menu_event(|app, event| {
                    let action = event.id.as_ref().to_owned();
                    if action == "show" { show_main(app); return; }
                    if action == "update" { updates::check(app.clone(), true); return; }
                    let handle = app.clone();
                    tauri::async_runtime::spawn_blocking(move || {
                        let result = match action.as_str() {
                            "export" => save_dialog(&handle, "/api/diagnostics", "MCUTOOL-诊断日志.zip").map(|_| ()),
                            "exit" => exit_desktop(&handle, false),
                            "stop" => exit_desktop(&handle, true),
                            _ => Ok(()),
                        };
                        if let Err(error) = result { show_error(&handle, &error); }
                    });
                }).build(app)?;
            app.manage(tray);
            if config_error.is_none() {
                let handle = app.handle().clone();
                let resource = app.path().resource_dir()?.join("runtime/MCUTOOL-service/MCUTOOL-service.exe");
                thread::spawn(move || {
                    let state = handle.state::<DesktopState>();
                    match Backend::start(&resource, &state.settings) {
                        Ok(backend) => {
                            let address = backend.info.url.parse();
                            if let Ok(mut target) = state.backend.lock() { *target = Some(backend.clone()); }
                            keepalive(handle.clone(), backend);
                            if !state.settings.test_mode { updates::check(handle.clone(), false); }
                            if let (Some(window), Ok(address)) = (handle.get_webview_window("main"), address) {
                                if window.navigate(address).is_err() {
                                    if let Ok(mut error) = state.error.lock() { *error = Some("工作台页面打开失败，请退出桌面端后重新打开".into()); }
                                }
                            }
                        }
                        Err(error) => {
                            backend::log_error(&state.settings, &error);
                            if let Ok(mut target) = state.error.lock() { *target = Some(error); }
                        }
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("MCU TOOL桌面窗口初始化失败");
}
