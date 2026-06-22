; Inno Setup script for ERP Estimate Generator
; ----------------------------------------------
; Compiled in CI with:  iscc /DMyAppVersion=<ver> installer\ERP_Estimate.iss
; Produces a per-user installer (no admin/UAC) so the in-app auto-updater can
; replace files and relaunch without elevation.
;
; Expects the PyInstaller one-folder build at:  dist\ERP_Estimate_v<ver>\
; (this is what build.py produces).

#ifndef MyAppVersion
  #define MyAppVersion "0.0"
#endif

#define MyAppName "ERP Estimate Generator"
#define MyAppExeName "ERP_Estimate.exe"
#define MyAppPublisher "Pramod Verma"
#define MySourceDir "..\dist\ERP_Estimate_v" + MyAppVersion

[Setup]
; A stable AppId keeps upgrades in-place across versions. Do not change it.
AppId={{B7E1F3A2-4C5D-4E6F-9A8B-1C2D3E4F5061}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ERP_Estimate
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ERP_Estimate_Setup_v{#MyAppVersion}
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running instance during (auto-)update so files can be replaced.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Relaunch the app after install / update finishes.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
