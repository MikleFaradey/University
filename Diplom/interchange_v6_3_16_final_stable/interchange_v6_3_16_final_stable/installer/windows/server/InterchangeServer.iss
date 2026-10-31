#define MyAppName "Interchange Server"
#define MyAppVersion "6.3.16"
#define MyAppExeName "InterchangeServer.exe"

[Setup]
AppId={{BD8F645E-952F-45B5-9632-22C283792A18
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Interchange
DefaultDirName={autopf}\Interchange Server
DefaultGroupName=Interchange
OutputDir=output
OutputBaseFilename=InterchangeServerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=..\client\interchange.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Files]
Source: "dist\InterchangeServer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Interchange Server"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Interchange Server"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start Interchange Server"; Flags: nowait postinstall skipifsilent

; User configuration, databases, PCAPs, downloads and received files
; are deliberately preserved on upgrade/uninstall.
