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
; El nombre lleva la versión: así no se confunde con un instalador descargado antes.
OutputBaseFilename=NejiPOS-Instalador-{#Version}
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

{ True si hay un Neji POS abierto en este computador (instalado o portátil, de cualquier carpeta). }
function NejiAbierto: Boolean;
var
  Localizador, Servicio, Procesos: Variant;
begin
  Result := False;
  try
    Localizador := CreateOleObject('WbemScripting.SWbemLocator');
    Servicio := Localizador.ConnectServer('.', 'root\CIMV2');
    Procesos := Servicio.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''NejiPOS.exe''');
    Result := Procesos.Count > 0;
  except
    Result := False;
  end;
end;

{ Antes de copiar los archivos: si Neji POS sigue abierto, se cierra. Si no, después de instalar se
  seguiría viendo la versión anterior (la nueva encuentra el puerto ocupado por la que está abierta). }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo, Intento: Integer;
begin
  Result := '';
  if not NejiAbierto then
    Exit;
  if not WizardSilent then
    if MsgBox('Neji POS está abierto. Para instalar la versión nueva hay que cerrarlo (lo que está guardado no se pierde).'
              + #13#10#13#10 + '¿Cerrarlo ahora?', mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := 'Cierra Neji POS y vuelve a abrir el instalador.';
      Exit;
    end;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM NejiPOS.exe', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  for Intento := 1 to 40 do
  begin
    if not NejiAbierto then
      Exit;
    Sleep(250);
  end;
  Result := 'No se pudo cerrar Neji POS. Ciérralo (o reinicia el computador) y vuelve a abrir el instalador.';
end;
