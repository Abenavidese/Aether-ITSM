# Política de acceso remoto por VPN — Andina Logística

## Alcance

Esta política aplica a todo empleado, contratista o proveedor que necesite
acceder a sistemas internos (ERP, intranet, bases de datos de reportes)
desde fuera de las oficinas. El acceso remoto a servidores de producción
NO se hace por VPN sino por el bastión con SSO (ver política de AWS IAM).

## Solicitud de acceso VPN

El acceso VPN se solicita con un ticket de categoría "Acceso" indicando
el motivo y la fecha de fin. Lo aprueba el jefe directo; para contratistas
lo aprueba además el dueño del contrato. El alta tarda como máximo un día
hábil después de la aprobación. Los accesos de contratistas vencen a los
90 días y deben renovarse con un nuevo ticket.

## Cliente VPN soportado

El único cliente permitido es FortiClient 7.2 o superior, instalado desde
el Portal de Software de la empresa. No se permite OpenVPN, WireGuard ni
clientes descargados de internet. En macOS hay que autorizar la extensión
de red en Ajustes del Sistema > Privacidad y seguridad la primera vez.

## Error ERR_VPN_809

El error ERR_VPN_809 ("el túnel no pudo establecerse") casi siempre se
debe a que la red local bloquea el puerto UDP 4500 (típico en hoteles y
redes de invitados). Pasos: 1) cambiar a la red del celular (hotspot);
2) en FortiClient activar "Usar TCP 443" en la configuración de la
conexión; 3) si persiste, cerrar sesión en FortiClient y volver a entrar
para renovar el certificado. Si con hotspot tampoco funciona, abrir ticket.

## Sesiones simultáneas

Cada usuario puede tener como máximo UNA sesión VPN activa. Si se conecta
desde un segundo equipo, la sesión anterior se cierra automáticamente. Un
aviso de "sesión duplicada" indica que la cuenta quedó conectada en otro
equipo: cerrar la sesión allí o esperar 15 minutos a que expire.

## Acceso desde el extranjero

Conectarse a la VPN desde fuera del país requiere avisar a Seguridad con
tres días de anticipación indicando país y fechas. Sin ese aviso, las
conexiones desde otro país se bloquean automáticamente por geolocalización.
Desde países sancionados no se permite el acceso en ningún caso.
