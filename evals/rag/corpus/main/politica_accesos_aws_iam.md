# Política de accesos a AWS (IAM)

## Roles permitidos

Los accesos a AWS se otorgan solo mediante roles de IAM Identity Center
(SSO); no se crean usuarios IAM con claves de acceso permanentes. Roles
disponibles: ReadOnly (lectura de consola), Developer (despliegues en
staging), DataAnalyst (Athena y S3 de reportes) y Admin (solo equipo de
plataforma).

## Aprobación del manager

Todo rol distinto de ReadOnly requiere aprobación del manager del
solicitante y del responsable de la cuenta AWS. El rol Admin requiere
además la aprobación del CTO. Las solicitudes sin justificación de negocio
se rechazan.

## Duración máxima de un acceso

Los roles Developer y DataAnalyst se otorgan por un máximo de 30 días. El
rol Admin se otorga por un máximo de 8 horas por solicitud. Al vencer, el
acceso se revoca automáticamente y debe pedirse de nuevo.

## Acceso de emergencia (break-glass)

En un incidente de severidad 1 fuera de horario, el ingeniero de guardia
puede usar la cuenta break-glass guardada en el gestor de secretos. Su uso
dispara una alerta a Seguridad y debe justificarse en el informe del
incidente dentro de las 24 horas siguientes.

## Revisión trimestral

Cada trimestre los managers revisan los accesos vigentes de su equipo. Los
accesos no confirmados en la revisión se revocan a los 7 días.
