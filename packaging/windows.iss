; SPDX-License-Identifier: GPL-3.0-or-later
; ProgramSource, OutputPath and AppVersion are supplied by build_installer.py.
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
LicenseFile={#ProgramSource}\LICENSE
SetupIconFile={#ProgramSource}\PadBridge.ico
UninstallDisplayIcon={app}\PadBridge.exe
UninstallDisplayName=PadBridge
AppMutex=Local\LittleChen12.PadBridge.Running
SetupMutex=Local\LittleChen12.PadBridge.Setup
CloseApplications=no
RestartApplications=no
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
Filename: "{app}\PadBridge.exe"; Parameters: "ui"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,PadBridge}"; Flags: nowait postinstall skipifsilent

[Messages]
en.SetupAppRunningError=PadBridge is running. Choose "Exit PadBridge" from its tray or window menu, then retry setup.
en.UninstallAppRunningError=PadBridge is running. Choose "Exit PadBridge" from its tray or window menu, then retry uninstall.
zh.SetupAppRunningError=PadBridge 正在运行。请从托盘或窗口菜单选择“退出 PadBridge”，然后继续安装。
zh.UninstallAppRunningError=PadBridge 正在运行。请从托盘或窗口菜单选择“退出 PadBridge”，然后继续卸载。
