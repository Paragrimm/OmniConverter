; Inno Setup script for the Windows installer.
; Built by packaging/build.py, which passes AppVersion, SourceDir, OutputDir and Root.
; Installs per user by default (no admin rights needed); an admin install is offered too.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Root
  #define Root "..\.."
#endif
#ifndef SourceDir
  #define SourceDir Root + "\dist\OmniConverter"
#endif
#ifndef OutputDir
  #define OutputDir Root + "\dist\release"
#endif

[Setup]
AppId={{B6E2F0A4-5C1D-4E8B-9A57-2F0C1D7E4A31}
AppName=OmniConverter
AppVersion={#AppVersion}
AppVerName=OmniConverter {#AppVersion}
AppPublisher=Paragrimm
AppPublisherURL=https://github.com/Paragrimm/OmniConverter
AppSupportURL=https://github.com/Paragrimm/OmniConverter/issues
DefaultDirName={autopf}\OmniConverter
DefaultGroupName=OmniConverter
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=OmniConverter-{#AppVersion}-windows-x64-setup
SetupIconFile={#Root}\src\omniconverter\resources\omniconverter.ico
UninstallDisplayIcon={app}\OmniConverter.exe
UninstallDisplayName=OmniConverter
LicenseFile={#Root}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.ContextMenu=Kontextmenü „Mit OmniConverter umwandeln“ im Explorer einrichten
en.ContextMenu=Add “Convert with OmniConverter” to the Explorer context menu
de.Integration=Integration:
en.Integration=Integration:

[Tasks]
Name: "contextmenu"; Description: "{cm:ContextMenu}"; GroupDescription: "{cm:Integration}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OmniConverter"; Filename: "{app}\OmniConverter.exe"
Name: "{autodesktop}\OmniConverter"; Filename: "{app}\OmniConverter.exe"; Tasks: desktopicon

[Run]
; Registered for the user who started the setup, also when it runs elevated.
Filename: "{app}\omniconvert.exe"; Parameters: "--integrate install"; Flags: runhidden runasoriginaluser; Tasks: contextmenu
Filename: "{app}\OmniConverter.exe"; Description: "{cm:LaunchProgram,OmniConverter}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\omniconvert.exe"; Parameters: "--integrate uninstall"; Flags: runhidden; RunOnceId: "RemoveContextMenu"
