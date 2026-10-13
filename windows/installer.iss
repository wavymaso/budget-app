; Inno Setup script: turns dist\Budget into Budget-Setup.exe.
; Built by GitHub Actions, or locally:  iscc /DVersion=1.7.0 windows\installer.iss
;
; Installs for the current user only (no admin rights needed) into
; %LOCALAPPDATA%\Programs\Budget. Your data stays in %APPDATA%\Budget, so
; updating or uninstalling the app never touches it.

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6F1C2E7A-8B4D-4C1E-9A57-3D2B1F0E9C41}
AppName=Budget
AppVersion={#Version}
AppPublisher=Budget
AppPublisherURL=https://github.com/wavymaso/budget-app
DefaultDirName={localappdata}\Programs\Budget
DefaultGroupName=Budget
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Budget-Setup-{#Version}
SetupIconFile=Budget.ico
UninstallDisplayIcon={app}\Budget.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Budget\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Budget"; Filename: "{app}\Budget.exe"
Name: "{autodesktop}\Budget"; Filename: "{app}\Budget.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Budget.exe"; Description: "Open Budget"; Flags: nowait postinstall skipifsilent
