; Inno Setup script for Parley. Build from the repository root after PyInstaller:
;   iscc /DAppVersion=1.0.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2B9A-4E0D-4B7E-9C51-7A3D2E8F1B42}
AppName=Parley
AppVersion={#AppVersion}
AppVerName=Parley {#AppVersion}
AppPublisher=Parley
AppPublisherURL=https://github.com/arkayaga/parley
AppSupportURL=https://github.com/arkayaga/parley/issues
DefaultDirName={localappdata}\Programs\Parley
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ParleySetup
SetupIconFile=..\assets\parley.ico
UninstallDisplayIcon={app}\Parley.exe
UninstallDisplayName=Parley
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Parley\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from older versions so stale modules never linger.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Parley"; Filename: "{app}\Parley.exe"
Name: "{autodesktop}\Parley"; Filename: "{app}\Parley.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Parley.exe"; Description: "Open Parley"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Parley.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function WebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup: Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if not WebView2Installed and not WizardSilent then
  begin
    // Detection can miss some setups, so only advise; never block the installation.
    if MsgBox('Parley uses the Microsoft Edge WebView2 Runtime, which may be missing on this computer.' + #13#10#13#10 +
              'Open its download page now? Parley will be installed either way.', mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;
