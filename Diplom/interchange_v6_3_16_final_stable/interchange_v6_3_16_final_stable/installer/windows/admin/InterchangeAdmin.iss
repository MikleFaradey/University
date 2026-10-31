#define MyAppName "Interchange Admin"
#define MyAppVersion "6.3.16"
#define MyAppExeName "InterchangeAdmin.exe"

[Setup]
AppId={{31CF8D6B-2110-4BB3-B1B5-2BB0470B2813
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Interchange
DefaultDirName={autopf}\Interchange Admin
DefaultGroupName=Interchange
OutputDir=output
OutputBaseFilename=InterchangeAdminSetup
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
Source: "dist\InterchangeAdmin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Interchange Admin"; Filename: "{app}\{#MyAppExeName}"


[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start Interchange Admin"; Flags: nowait postinstall skipifsilent

; User configuration, databases, PCAPs, downloads and received files
; are deliberately preserved on upgrade/uninstall.
