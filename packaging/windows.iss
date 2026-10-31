; SPDX-License-Identifier: GPL-3.0-or-later
; ProgramSource, OutputPath and AppVersion are supplied by build_installer.py.
#include ComponentDefinitions
[Setup]
AppId=LittleChen12.PadBridge
AppName=PadBridge
AppVersion={#AppVersion}
AppPublisher=LittleChen12
AppPublisherURL=https://github.com/LittleChen12/Pad_Bridge
AppSupportURL=https://github.com/LittleChen12/Pad_Bridge/issues
AppUpdatesURL=https://github.com/LittleChen12/Pad_Bridge/releases/latest
DefaultDirName={localappdata}\Programs\PadBridge
DefaultGroupName=PadBridge
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
SetupArchitecture=x64
WizardStyle=modern dynamic
DisableProgramGroupPage=yes
LicenseFile={#InstallerLicense}
SetupIconFile={#ProgramSource}\PadBridge.ico
UninstallDisplayIcon={app}\PadBridge.exe
UninstallDisplayName=PadBridge
AppMutex=Local\LittleChen12.PadBridge.Running
SetupMutex=Local\LittleChen12.PadBridge.Setup
CloseApplications=no
RestartApplications=no
SetupLogging=yes
OutputDir={#OutputPath}
OutputBaseFilename=padbridge-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription=PadBridge Setup
VersionInfoProductName=PadBridge
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#ProgramSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PadBridge"; Filename: "{app}\PadBridge.exe"; Parameters: "ui"; WorkingDir: "{app}"; AppUserModelID: "LittleChen12.PadBridge"
Name: "{autodesktop}\PadBridge"; Filename: "{app}\PadBridge.exe"; Parameters: "ui"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "LittleChen12.PadBridge"

[Run]
Filename: "{app}\PadBridge.exe"; Parameters: "ui"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,PadBridge}"; Flags: nowait postinstall skipifsilent; Check: CanLaunchApp

[Messages]
en.SetupAppRunningError=PadBridge is running. Choose "Exit PadBridge" from its tray or window menu, then retry setup.
en.UninstallAppRunningError=PadBridge is running. Choose "Exit PadBridge" from its tray or window menu, then retry uninstall.
zh.SetupAppRunningError=PadBridge 正在运行。请从托盘或窗口菜单选择“退出 PadBridge”，然后继续安装。
zh.UninstallAppRunningError=PadBridge 正在运行。请从托盘或窗口菜单选择“退出 PadBridge”，然后继续卸载。

[CustomMessages]
en.ComponentsStatus=Checking USB and extended-display components...
zh.ComponentsStatus=正在检查 USB 和扩展屏幕组件……
en.ComponentsInstall=Configuring USB and extended-display components. Please respond to the Windows confirmation dialog.
zh.ComponentsInstall=正在配置 USB 和扩展屏幕组件，请留意 Windows 确认窗口。
en.DownloadTitle=Preparing USB connection
zh.DownloadTitle=准备 USB 连接
en.DownloadDescription=Setup is downloading the required USB component from Apple. No separate download is needed.
zh.DownloadDescription=安装器正在从 Apple 官方下载所需 USB 组件，无需另行下载或操作。
en.ComponentsError=Component setup did not finish. Click Back and Install to retry. Details:
zh.ComponentsError=组件配置未完成，请点击“上一步”后重新安装。详细信息：
en.ComponentsConflict=Another application owns the Virtual Display Driver. Resolve this conflict before retrying; existing display settings have been preserved.
zh.ComponentsConflict=检测到其他软件管理的 Virtual Display Driver，请处理该驱动后重试。现有显示配置已保留。
en.ComponentsMemo=USB and extended-display components: automatically detect, install and verify. If USB support is missing, Setup downloads it from Apple (about 39 MB). Allow Windows administrator / driver confirmation when prompted.
zh.ComponentsMemo=USB 与扩展屏幕组件：自动检测、安装并验证。缺少 USB 支持时由安装器从 Apple 官方下载（约 39 MB）。首次配置请允许 Windows 管理员及驱动发布者确认。
en.ApplicationOnly=Application-only deployment was explicitly selected on the command line. USB and extended-display components will not be configured.
zh.ApplicationOnly=命令行已明确选择仅部署主程序，本次不会配置 USB 与扩展屏幕组件。

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ComponentsExtracted, ComponentsDone, ComponentRestart: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(CustomMessage('DownloadTitle'),
    CustomMessage('DownloadDescription'), nil);
end;

function CanLaunchApp: Boolean;
begin
  Result := not ComponentRestart;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfoInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfoInfo + NewLine + NewLine + MemoTasksInfo + NewLine + NewLine +
    CustomMessage('ComponentsMemo');
  if ExpandConstant('{param:APPLICATIONONLY|0}') = '1' then
    Result := MemoDirInfoInfo + NewLine + NewLine + CustomMessage('ApplicationOnly');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Helper, Report, Params, ApplePackage, LogDir, Verb: String;
  ExitCode: Integer;
begin
  Result := '';
  if ComponentsDone then exit;
  { Explicit deployment/testing switch; never inferred from errors or environment.
    Default interactive and silent installs both require every component. }
  if ExpandConstant('{param:APPLICATIONONLY|0}') = '1' then begin
    Log(CustomMessage('ApplicationOnly'));
    ComponentsDone := True;
    exit;
  end;
  WizardForm.PreparingLabel.Caption := CustomMessage('ComponentsStatus');
  try
    if not ComponentsExtracted then begin
      { Use the exact application and dependencies contained in this installer.
        ExtractTemporaryFiles preserves the unexpanded destination subdirectory. }
      ExtractTemporaryFiles('{app}\PadBridge.exe');
      ExtractTemporaryFiles('{app}\_internal\*');
      ComponentsExtracted := True;
    end;
    Helper := ExpandConstant('{tmp}\') + '{app}\PadBridge.exe';
    Report := ExpandConstant('{tmp}\components.ini');
    Params := 'setup-components --check --result "' + Report + '"';
    if not Exec(Helper, Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException(SysErrorMessage(ExitCode));
    if (ExitCode <> 0) or not FileExists(Report) then
      RaiseException(GetIniString('components', 'error', 'Component check failed.', Report));
    if GetIniString('components', 'display', '', Report) = 'conflict' then
      RaiseException(CustomMessage('ComponentsConflict'));
    if (GetIniString('components', 'apple', '', Report) = 'ready') and
       (GetIniString('components', 'display', '', Report) = 'ready') then begin
      ComponentsDone := True;
      exit;
    end;
    ApplePackage := '';
    if GetIniString('components', 'apple', '', Report) = 'missing' then begin
      DownloadPage.Clear;
      DownloadPage.Add('{#AppleURL}', 'AppleMobileDeviceSupport64.msi', '{#AppleSHA256}');
      DownloadPage.Show;
      try
        DownloadPage.Download;
      finally
        DownloadPage.Hide;
      end;
      ApplePackage := ExpandConstant('{tmp}\AppleMobileDeviceSupport64.msi');
    end;
    { The application stays per-user. Only this short-lived helper is elevated;
      it installs the signed system components and has no persistent authority. }
    DeleteFile(Report);
    LogDir := ExpandConstant('{localappdata}\PadBridge\setup-logs');
    ForceDirectories(LogDir);
    Params := 'setup-components --result "' + Report + '" --setup-log-dir "' + LogDir + '"';
    if ApplePackage <> '' then Params := Params + ' --apple-package "' + ApplePackage + '"';
    if not WizardSilent then Params := Params + ' --interactive';
    WizardForm.PreparingLabel.Caption := CustomMessage('ComponentsInstall');
    if IsAdmin then Verb := '' else Verb := 'runas';
    if not ShellExec(Verb, Helper, Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException(SysErrorMessage(ExitCode));
    if FileExists(Report) then FileCopy(Report, LogDir + '\components.ini', False);
    if (ExitCode <> 0) or not FileExists(Report) then
      RaiseException(GetIniString('components', 'error', 'Component installation failed.', Report));
    if not ((GetIniString('components', 'apple', '', Report) = 'ready') or
            (GetIniString('components', 'apple', '', Report) = 'restart')) then
      RaiseException('USB component verification failed.');
    if not ((GetIniString('components', 'display', '', Report) = 'ready') or
            (GetIniString('components', 'display', '', Report) = 'restart')) then
      RaiseException('Display component verification failed.');
    ComponentRestart := GetIniString('components', 'restart', '0', Report) = '1';
    ComponentsDone := True;
  except
    Result := CustomMessage('ComponentsError') + #13#10 + GetExceptionMessage;
    Log(Result);
  end;
end;

function NeedRestart: Boolean;
begin
  Result := ComponentRestart;
end;
