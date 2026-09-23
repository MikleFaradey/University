#define MyAppName "Interchange"
#define MyAppVersion "6.3.16"
#define MyAppPublisher "Interchange"
#define MyAppExeName "Interchange.exe"

[Setup]
AppId={{7A42E2B1-0D32-4D80-B406-1E0D1F89A511}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Interchange
DefaultGroupName=Interchange
OutputDir=output
OutputBaseFilename=InterchangeClientSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=interchange.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
UsePreviousAppDir=no
UsePreviousTasks=no

[Files]
Source: "dist\Interchange\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Interchange"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Interchange"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start Interchange"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{%USERPROFILE}\.config\interchange"
Type: filesandordirs; Name: "{%USERPROFILE}\.interchange"
Type: filesandordirs; Name: "{%USERPROFILE}\InterchangeReceived"
Type: filesandordirs; Name: "{%USERPROFILE}\InterchangeServerReceived"
Type: filesandordirs; Name: "{userappdata}\Interchange"
Type: filesandordirs; Name: "{localappdata}\Interchange"

[Code]
procedure RemoveDirTree(const Path: String);
begin
  if DirExists(Path) then
    DelTree(Path, True, True, True);
end;

procedure RemoveFileIfPresent(const Path: String);
begin
  if FileExists(Path) then
    DeleteFile(Path);
end;

procedure CleanInterchangeState;
begin
  RemoveDirTree(ExpandConstant('{%USERPROFILE}\.config\interchange'));
  RemoveDirTree(ExpandConstant('{%USERPROFILE}\.interchange'));
  RemoveDirTree(ExpandConstant('{%USERPROFILE}\InterchangeReceived'));
  RemoveDirTree(ExpandConstant('{%USERPROFILE}\InterchangeServerReceived'));
  RemoveDirTree(ExpandConstant('{userappdata}\Interchange'));
  RemoveDirTree(ExpandConstant('{localappdata}\Interchange'));
  RemoveDirTree(ExpandConstant('{app}'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CleanInterchangeState;
  Result := '';
end;
