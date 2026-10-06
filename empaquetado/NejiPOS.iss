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
; Instalador oficial de Microsoft Edge WebView2: solo se usa si el equipo no lo tiene.
Source: "..\build\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: FaltaWebView2

[Icons]
Name: "{autoprograms}\Neji POS"; Filename: "{app}\NejiPOS.exe"
Name: "{autodesktop}\Neji POS"; Filename: "{app}\NejiPOS.exe"; Tasks: escritorio

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Instalando Microsoft Edge WebView2 (necesario para la ventana de Neji POS)..."; Flags: waituntilterminated; Check: FaltaWebView2
Filename: "{app}\NejiPOS.exe"; Description: "Abrir Neji POS"; Flags: nowait postinstall skipifsilent

[Code]
const
  CLAVE_WEBVIEW2 = '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function VersionValida(Raiz: Integer; Ruta: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Raiz, Ruta, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

{ True si Microsoft Edge WebView2 Runtime no está instalado (ni para el equipo ni para el usuario). }
function FaltaWebView2: Boolean;
begin
  Result := not (VersionValida(HKLM, 'SOFTWARE\WOW6432Node' + CLAVE_WEBVIEW2)
              or VersionValida(HKLM, 'SOFTWARE' + CLAVE_WEBVIEW2)
              or VersionValida(HKCU, 'Software' + CLAVE_WEBVIEW2));
end;
