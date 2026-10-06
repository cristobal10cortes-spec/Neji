; Instalador de Neji POS (Inno Setup 6). Se compila después de PyInstaller:
;     iscc empaquetado\NejiPOS.iss      ->  dist\NejiPOS-Instalador.exe
; Instala para el usuario actual (no pide administrador) en %LOCALAPPDATA%\Programs\Neji POS.
; Los datos del negocio quedan en %LOCALAPPDATA%\NejiPOS\datos: ni actualizar ni desinstalar
; los borra.

#define Version GetEnv("NEJI_VERSION")
#if Version == ""
  #define Version "0.0.0"
#endif

[Setup]
AppId={{8C5D3F2A-6B1E-4E7A-9C34-5A2F1B7D9E10}
AppName=Neji POS
AppVersion={#Version}
AppVerName=Neji POS {#Version}
AppPublisher=Neji POS
DefaultDirName={localappdata}\Programs\Neji POS
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=NejiPOS-Instalador
SetupIconFile=neji.ico
UninstallDisplayIcon={app}\NejiPOS.exe
UninstallDisplayName=Neji POS
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[InstallDelete]
; Al actualizar, borra las librerías de la versión anterior (los datos están en otra carpeta).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\NejiPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Neji POS"; Filename: "{app}\NejiPOS.exe"
Name: "{autodesktop}\Neji POS"; Filename: "{app}\NejiPOS.exe"; Tasks: escritorio

[Run]
Filename: "{app}\NejiPOS.exe"; Description: "Abrir Neji POS"; Flags: nowait postinstall skipifsilent
