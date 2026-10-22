#ifndef ReleaseDir
  #define ReleaseDir "..\dist\TachiTalk"
#endif
#ifndef ServiceDir
  #define ServiceDir "..\services\gpt_sovits"
#endif
#ifndef OutputDirectory
  #define OutputDirectory "..\dist\installer"
#endif
[Setup]
AppId={{ABD38416-108D-4C54-9044-BC4E59DD3D83}
AppName=TachiTalk
AppVersion=0.2.0
AppPublisher=TachiTalk
DefaultDirName={autopf}\TachiTalk
DefaultGroupName=TachiTalk
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDirectory}
OutputBaseFilename=TachiTalk_setup
DiskSpanning=yes
DiskSliceSize=max
SetupIconFile=app.ico
UninstallDisplayIcon={app}\TachiTalk.exe
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
CloseApplications=yes
CloseApplicationsFilter=TachiTalk.exe,python.exe,*.dll,*.pyd
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=安装说明.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#ReleaseDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ServiceDir}\*"; DestDir: "{app}\services\gpt_sovits"; Excludes: "__pycache__,*.pyc,*.pyo,*.log,*.tmp,TEMP,cache,.git"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "安装说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; 整体替换私有运行环境，防止旧CUDA DLL残留混入新版本。
Type: filesandordirs; Name: "{app}\services\gpt_sovits\runtime"

[Icons]
Name: "{autoprograms}\TachiTalk"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\TachiTalk.exe"
Name: "{autodesktop}\TachiTalk"; Filename: "{app}\TachiTalk.exe"; WorkingDir: "{app}"; IconFilename: "{app}\TachiTalk.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TachiTalk.exe"; Description: "启动 TachiTalk"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
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
