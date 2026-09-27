# Política de software y gestión de dispositivos (MDM)

## Catálogo de software aprobado

El software aprobado se instala solo desde el Portal de Software (MDM
Intune). Paquetes del catálogo: pkg_office365 (Microsoft 365), pkg_vscode
(Visual Studio Code), pkg_docker (Docker Desktop), pkg_zoom (Zoom),
pkg_forticlient (FortiClient VPN) y pkg_dbeaver (DBeaver). Todo paquete del
catálogo se autoinstala sin aprobación adicional.

## Docker Desktop

Docker Desktop requiere licencia de pago por usuario. Para recibirlo el
usuario debe pertenecer al grupo de MDM "pkg_docker", que se asigna por
ticket con aprobación del jefe del área técnica. Sin ese grupo, el
paquete no aparece en el portal. Alternativa sin licencia: Podman.

## Software no catalogado

Para instalar algo que no está en el catálogo se abre un ticket con el
nombre, la versión, el enlace oficial y el uso previsto. Seguridad lo
evalúa en un máximo de 5 días hábiles. No se permite instalar software
descargado directamente de internet aunque el usuario tenga permisos de
administrador local.

## Desinstalación y equipos no conformes

Un equipo con software no autorizado queda marcado como "no conforme" en
el MDM y pierde acceso al correo y a la VPN hasta que se corrija. El MDM
desinstala automáticamente las aplicaciones de la lista de bloqueo
(torrents, VPNs personales, acceso remoto no autorizado como AnyDesk).
