#ifndef ReleaseDir
  #define ReleaseDir "..\dist\TachiTalk"
#endif
#ifndef VoiceDir
  #define VoiceDir "..\build\modular\voice-stage"
#endif
#ifndef MainOnly
  #define MainOnly 0
#endif
#ifndef QAMode
  #define QAMode 0
#endif
#ifndef TestBuild
  #define TestBuild 0
#endif
#ifndef OutputDirectory
  #define OutputDirectory "..\dist\installer"
#endif
[Setup]
#if Int(QAMode)
AppId={{97CB57C4-BD64-4535-8762-427674F9659C}
CreateUninstallRegKey=no
Uninstallable=no
#elif Int(TestBuild)
AppId=TachiTalk-Test-2.0.0
#else
AppId={{ABD38416-108D-4C54-9044-BC4E59DD3D83}
#endif
#if Int(TestBuild)
AppName=TachiTalk 测试版 2.0.0
#else
AppName=TachiTalk
#endif
AppVersion=2.0.0
AppPublisher=TachiTalk
#if Int(TestBuild)
DefaultDirName={localappdata}\Programs\TachiTalk-Test-2.0.0
DefaultGroupName=TachiTalk 测试版 2.0.0
#else
DefaultDirName={localappdata}\Programs\TachiTalk
DefaultGroupName=TachiTalk
#endif
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDirectory}
#if Int(MainOnly)
OutputBaseFilename=TachiTalk_main_setup
#else
OutputBaseFilename=TachiTalk_setup
#endif
DiskSpanning=yes
DiskSliceSize=1900000000
SetupIconFile=app.ico
UninstallDisplayIcon={app}\TachiTalk.exe
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
#if Int(TestBuild)
CloseApplications=no
#else
CloseApplications=yes
#endif
CloseApplicationsFilter=TachiTalk.exe
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=安装说明.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："
Name: "downloadvoice"; Description: "安装结束后打开语音资源下载面板（失败可跳过，主程序正常使用）"; GroupDescription: "可选语音："; Flags: unchecked

[Types]
Name: "main"; Description: "仅安装主程序"
#if Int(MainOnly) == 0
Name: "full"; Description: "完整离线安装（主程序与语音）"
#endif
Name: "custom"; Description: "自定义安装"; Flags: iscustom

[Components]
#if Int(MainOnly)
Name: "main"; Description: "TachiTalk 主程序"; Types: main custom; Flags: fixed
#else
Name: "main"; Description: "TachiTalk 主程序"; Types: main full custom; Flags: fixed
#endif
#if Int(MainOnly) == 0
Name: "voice"; Description: "GPT-SoVITS v2ProPlus 语音环境和模型（可选）"; Types: full custom
#endif

[Files]
Source: "{#ReleaseDir}\*"; DestDir: "{app}"; Excludes: "\assets,\user_data"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#ReleaseDir}\assets\*"; DestDir: "{app}\assets"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs; Components: main
#if Int(MainOnly) == 0
Source: "{#VoiceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: voice
#endif
Source: "安装说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
#if Int(QAMode) == 0
#if Int(TestBuild)
Name: "{autoprograms}\TachiTalk 测试版 2.0.0"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\resources\control_panel\assets\tachitalk.ico"; AppUserModelID: "TachiTalk.Desktop.Test"
Name: "{autodesktop}\TachiTalk 测试版 2.0.0"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\resources\control_panel\assets\tachitalk.ico"; AppUserModelID: "TachiTalk.Desktop.Test"; Tasks: desktopicon
#else
Name: "{autoprograms}\TachiTalk"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\resources\control_panel\assets\tachitalk.ico"; AppUserModelID: "TachiTalk.Desktop"
Name: "{autodesktop}\TachiTalk"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\resources\control_panel\assets\tachitalk.ico"; AppUserModelID: "TachiTalk.Desktop"; Tasks: desktopicon
#endif
#endif

[Run]
#if Int(QAMode) == 0
Filename: "{app}\TachiTalk.exe"; Parameters: "{code:GetLaunchParameters}"; Description: "启动 TachiTalk / 可选语音下载"; Flags: nowait postinstall skipifsilent runasoriginaluser
#endif

[Code]
function GetLaunchParameters(Param: String): String;
begin
  Result := '';
  if WizardIsTaskSelected('downloadvoice') then Result := '--install-voice';
end;

procedure InitializeWizard();
var
  OldDirectory: String;
begin
#if (Int(QAMode) == 0) && (Int(TestBuild) == 0)
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{ABD38416-108D-4C54-9044-BC4E59DD3D83}_is1', 'InstallLocation', OldDirectory) or
     RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{ABD38416-108D-4C54-9044-BC4E59DD3D83}_is1', 'InstallLocation', OldDirectory) then
    if FileExists(AddBackslash(OldDirectory) + 'TachiTalk.exe') then
      WizardForm.DirEdit.Text := OldDirectory;
#endif
end;

function InitializeSetup(): Boolean;
var
  DataFilename: String;
begin
  DataFilename := ChangeFileExt(ExpandConstant('{srcexe}'), '') + '-1.bin';
  Result := FileExists(DataFilename);
  if not Result then
    MsgBox('找不到安装数据文件：' + ExtractFileName(DataFilename) + #13#10#13#10 +
      '请先将压缩包全部解压，确保 EXE 与对应的 -1.bin 文件位于同一文件夹。' + #13#10 +
      '不要只运行压缩包内的 EXE，也不要单独更改某一个文件的名称。', mbError, MB_OK);
end;
